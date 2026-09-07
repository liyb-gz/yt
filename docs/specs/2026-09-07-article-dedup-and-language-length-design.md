# Article Deduplication and Per-Language Lengths

**Status:** Design specification
**Date:** 2026-09-07

## Summary

Add two related article-output capabilities:

1. Optional metadata-based deduplication in the configured article directory,
   with an option to include nested subfolders.
2. Independent article length selection for each target language, while
   retaining the current global length as the fallback.

Deduplication is intentionally limited to Markdown article output. It is
available only when `output.article.metadata` is `frontmatter`, because
frontmatter is the machine-readable identity record. Subtitle formats do not
participate in this feature in this iteration.

## Goals and Non-Goals

### Goals

- Prevent regenerating an article when an article for the same video, language,
  and length profile already exists, even if its filename date differs.
- Keep the existing article filename convention compatible for the default
  `original` profile where practical.
- Allow a configuration such as Traditional Chinese `original` and Korean
  `short` in one invocation.
- Make precedence and failure behavior explicit and testable.

### Non-Goals

- Deduplicating SRT, VTT, or TXT files.
- Deleting or rewriting existing files during a dedup scan.
- Content similarity or semantic duplicate detection.
- Automatic migration of legacy subtitle files.

## Configuration

Extend `output.article` with:

```yaml
output:
  format: article
  article:
    length: original          # global fallback
    length_by_language:       # optional exact language-code overrides
      zh-TW: original
      ko: short
    metadata: frontmatter
    dedup:
      enabled: true
      recursive: false
```

### Validation

- `length` and every `length_by_language` value must be one of
  `original`, `long`, `medium`, or `short`.
- Language override keys must be non-empty strings.
- `dedup.enabled: true` requires `metadata: frontmatter`; configuration
  loading fails with an actionable `ValueError` otherwise.
- Dedup settings have effect only for `output.format: article`. For other
  formats, dedup is not attempted; the invalid metadata combination above is
  still rejected so that enabling a feature that cannot work is never silent.
- Defaults preserve current behavior: `length_by_language` is empty,
  `dedup.enabled` is false, and `dedup.recursive` is false.

### Length precedence

For each requested language, resolve the profile in this order:

1. CLI `--length`, when supplied. This explicit flag applies to every target
   language and therefore intentionally overrides all configured per-language
   values.
2. `output.article.length_by_language[language]`, when an exact key exists.
3. `output.article.length`.

The resolved profile is passed to the existing per-call
`generate_article(..., length=...)` API and is recorded in frontmatter.

## Frontmatter Identity Schema

When `metadata: frontmatter`, newly generated articles include these fields in
their YAML frontmatter:

```yaml
---
schema_version: 1
title: "..."
author: "..."
url: https://www.youtube.com/watch?v=VIDEO_ID
video_id: VIDEO_ID
language: zh-TW
profile: original
upload_date: 2026-09-05
request_date: 2026-09-07
---
```

`output_type` is not serialized because this frontmatter mode is used only for
article files; the scanner treats every accepted Markdown record as
`output_type: article` internally. The deduplication identity is therefore:

`video_id + article + language + profile`

The writer must produce valid YAML when titles or authors contain quotes,
backslashes, or line breaks. `schema_version` allows future schema changes
without guessing at field meanings.

## Deduplication Behavior

### Scan root and recursion

- The scan root is `storage.article_dir`.
- With `recursive: false`, inspect Markdown files directly in that directory.
- With `recursive: true`, inspect Markdown files in the directory and all
  descendant directories.
- Only regular `.md` files are candidates. Files outside the configured root
  are never considered.

### Matching

Before fetching a transcript or calling the LLM for a language, scan candidate
files and parse their leading YAML frontmatter block. A file is a duplicate
only when all of these fields match exactly after trimming surrounding
whitespace:

- `video_id` (the YouTube ID from the current video metadata)
- `language` (the requested language code)
- `profile` (the resolved article length)

The article output type is implicit as described above. The request date,
upload date, title, author, filename, and file contents do not affect identity.

If multiple files match, skip generation and report all matching paths (or a
count plus the first path when normal output is abbreviated). No files are
removed automatically.

### Existing path and force behavior

- The current exact output-path existence check remains as a compatibility
  guard. Without `--force`, an existing target path is skipped even if its
  metadata is missing or does not match.
- Metadata dedup additionally skips when a matching record is found at another
  path, which handles request-date or upload-date filename changes.
- `--force` bypasses both skip checks for the current language and permits
  regeneration. It may overwrite the deterministic target path but never
  deletes other matching files.
- A dedup skip must occur before transcript fetching and article generation.

### Profile-aware filenames

The current filename does not contain article length, so different profiles for
the same language would otherwise collide. Preserve existing names for the
`original` profile. For non-`original` profiles, append the profile to the
language portion, for example:

`2026-09-07 - Title [ko] [short].md`

The frontmatter remains authoritative; this suffix is only a collision-avoidance
and discoverability aid.

### Legacy articles

Older frontmatter contains `url`, but not the new identity fields. The scanner
may parse and validate the URL, but it must not infer a profile that is not
recorded. A legacy file is eligible for dedup only when `video_id`, `language`,
and `profile` can be proven without relying on title/date guesses. Otherwise it
is ignored for metadata matching and remains subject to the normal exact-path
check. This conservative policy avoids suppressing a requested profile based on
an unverifiable old article.

### Malformed or unreadable metadata

- Invalid YAML, missing required fields, and unreadable files are ignored for
  metadata matching with a warning in verbose mode.
- A scan failure for one file must not abort processing of the video.
- The newly written article and its metadata must be flushed as one normal save
  operation; a partially written frontmatter block must never be considered a
  valid duplicate.

## Processing Flow

For each video and target language:

1. Resolve the article profile using the precedence rules above.
2. Compute the deterministic output path (including a non-original profile
   suffix when needed).
3. Apply `--force` and exact-path checks.
4. If article dedup is enabled, scan the configured root and apply metadata
   matching. Skip before network transcript or LLM work when a duplicate is
   found.
5. Fetch/translate the source transcript and generate the article with the
   resolved profile.
6. Add enriched frontmatter, including the resolved language and profile.
7. Save the Markdown file and report the profile and dedup decision in status
   output.

## CLI and User-Facing Behavior

- No new CLI flag is required for per-language lengths; the mapping is
  configuration-driven and works with the existing `--languages` selection.
- Existing `--length` remains a global one-shot override for all languages.
- Existing `--force` semantics are retained and explicitly bypass dedup.
- Configuration errors (for example, dedup enabled with `metadata: header`)
  are reported before any video is processed.
- A skipped article should identify the language, profile, and matching path so
  users can distinguish a metadata dedup skip from an exact filename skip.

## Testing Requirements

Add focused tests covering:

- Parsing and validation of `length_by_language` and dedup settings.
- Rejection of dedup when article metadata is not `frontmatter`.
- Length resolution for override, mapped, and fallback cases, including CLI
  override precedence.
- Frontmatter generation and YAML escaping for special characters.
- Metadata matching when the filename/request date differs.
- Recursive versus non-recursive scans.
- Missing fields, malformed YAML, and unreadable files being ignored safely.
- `--force` bypassing both dedup and existing-path skips.
- Profile-aware filenames preventing collisions between `original` and
  non-original articles.
- Ensuring a duplicate skip avoids transcript and LLM calls.

## Deferred Subtitle Deduplication Decision Record

Subtitle outputs currently have no machine-readable metadata, and adding YAML
frontmatter would make SRT/TXT invalid or non-portable (VTT has comments, but
not a shared schema across all consumers). Subtitle dedup is therefore deferred
until a metadata transport is chosen.

Two candidate designs remain documented for that future work:

- **Per-output sidecars:** write one JSON metadata file beside each subtitle.
  Metadata travels with a renamed file and has simple crash recovery, but adds
  visible files and requires scanning many small records.
- **Per-directory manifest:** write one JSON index under each target directory.
  Lookup is fast and folders stay tidy, but manual moves/renames can stale the
  index and require reconciliation.

No sidecar or manifest files should be created by this article-only change.

