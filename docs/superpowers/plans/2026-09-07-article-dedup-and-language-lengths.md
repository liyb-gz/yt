# Article Deduplication and Per-Language Lengths Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add frontmatter-backed article deduplication with optional recursive scanning and allow each article language to use its own length profile.

**Architecture:** Keep configuration and CLI precedence in src/yt/config.py and src/yt/cli.py. Add a focused src/yt/article.py module for article identity types, frontmatter parsing, profile resolution support, and directory scanning; keep article text formatting in src/yt/utils.py. process_video resolves one profile per language, checks exact paths and metadata duplicates before network work, and writes enriched frontmatter.

**Tech Stack:** Python 3.11 dataclasses, pathlib, PyYAML, pytest, existing Rich CLI and YouTube/LLM clients.

**Spec:** docs/specs/2026-09-07-article-dedup-and-language-length-design.md

## Global Constraints

- Deduplication applies only to Markdown articles and requires output.article.metadata: frontmatter.
- Deduplication identity is video_id + article + language + profile; output_type is implicit and is not serialized.
- recursive false scans only storage.article_dir; recursive true scans descendant Markdown files.
- Subtitle formats receive no sidecar or manifest metadata in this change.
- Article length precedence is CLI --length, then exact length_by_language, then global length.
- --force bypasses exact-path and metadata dedup checks without deleting other files.
- Preserve the existing filename for original; append [profile] for non-original profiles.
- Malformed, unreadable, or incomplete frontmatter is ignored for metadata matching and must not abort processing.

---

### Task 1: Extend article configuration and profile resolution

**Files:**
- Modify src/yt/config.py: ArticleConfig and Config.from_dict
- Modify src/yt/cli.py: DEFAULT_CONFIG_CONTENT, cmd_config_show, cmd_process_urls
- Create tests/test_article_config.py

**Interfaces:**
- Add ArticleDedupConfig(enabled: bool = False, recursive: bool = False).
- Add ArticleConfig.resolve_length(language: str, cli_override: str | None = None) -> str.
- process_video receives article_length: str | None; None means no CLI override and configuration resolves per language.

- [ ] Write failing tests for loading length_by_language and dedup, CLI precedence, invalid lengths, and rejection of dedup unless metadata is frontmatter.
- [ ] Run: pytest tests/test_article_config.py -q. Expected: failure because the new fields and resolver do not exist.
- [ ] Implement ArticleDedupConfig, ArticleConfig fields, resolve_length, and validation for all allowed profiles and non-empty string language keys.
- [ ] Parse dedup enabled and recursive booleans. Reject enabled dedup unless metadata is frontmatter with an actionable ValueError.
- [ ] Add the new keys to DEFAULT_CONFIG_CONTENT and config show output.
- [ ] Pass args.length (including None) into process_video instead of resolving the global config length in CLI.
- [ ] Run pytest tests/test_article_config.py -q. Expected: pass.
- [ ] Commit with: git add src/yt/config.py src/yt/cli.py tests/test_article_config.py && git commit -m "feat: add per-language article configuration"

---

### Task 2: Add safe enriched frontmatter and article identity parsing

**Files:**
- Create src/yt/article.py
- Modify src/yt/utils.py: format_article_with_metadata
- Create tests/test_article_metadata.py

**Interfaces:**
- ArticleIdentity(video_id: str, language: str, profile: str).
- parse_article_frontmatter(text: str) -> dict[str, object] | None.
- frontmatter_identity(text: str) -> ArticleIdentity | None.
- format_article_with_metadata continues to support frontmatter, header, footer, and none, with required language and profile arguments.

- [ ] Add failing tests that assert enriched fields, YAML escaping, and rejection of incomplete or malformed frontmatter.
- [ ] Run: pytest tests/test_article_metadata.py -q. Expected: failure because the module and signature do not exist.
- [ ] Implement parsing of only a leading YAML block delimited by standalone --- lines. Use yaml.safe_load and return None for malformed, non-mapping, or incomplete data. Trim identity strings and require video_id, language, and profile.
- [ ] Serialize frontmatter with yaml.safe_dump(sort_keys=False, allow_unicode=True), schema_version 1, existing fields, video_id, language, and profile. Keep non-frontmatter styles behavior unchanged apart from accepting the new arguments.
- [ ] Update all call sites and tests for the new arguments.
- [ ] Run pytest tests/test_article_metadata.py -q. Expected: pass.
- [ ] Commit with: git add src/yt/article.py src/yt/utils.py tests/test_article_metadata.py && git commit -m "feat: enrich article frontmatter"

---

### Task 3: Implement recursive metadata duplicate scanning

**Files:**
- Modify src/yt/article.py
- Create tests/test_article_dedup.py

**Interface:** find_duplicate_articles(root: Path, identity: ArticleIdentity, recursive: bool = False) -> list[Path].

- [ ] Add failing tests for filename-independent matching, recursive versus non-recursive behavior, and malformed/incomplete files being ignored.
- [ ] Run: pytest tests/test_article_dedup.py -q. Expected: failure because the scanner does not exist.
- [ ] Enumerate sorted root.glob("*.md") or root.rglob("*.md"), keep regular files, read UTF-8, catch OSError and parser errors, and continue. Return paths whose frontmatter_identity equals the requested identity. Return an empty list when root is absent.
- [ ] Run pytest tests/test_article_dedup.py -q. Expected: pass.
- [ ] Commit with: git add src/yt/article.py tests/test_article_dedup.py && git commit -m "feat: add recursive article dedup scanning"

---

### Task 4: Integrate profile resolution, dedup, and profile-aware filenames

**Files:**
- Modify src/yt/transcript.py: process_video
- Modify src/yt/utils.py: format_output_filename
- Create tests/test_article_processing.py

**Interfaces:**
- process_video(..., article_length: str | None = None, ...) resolves one profile per language.
- format_output_filename(..., profile: str | None = None) appends [profile] only when profile is non-None and non-original.
- Dedup checks occur only when saving article output and config.output.article.dedup.enabled is true.

- [ ] Add failing orchestration tests with fake VideoMetadata and monkeypatched transcript/LLM calls. Verify a matching article skips both calls, and verify zh-TW original plus ko short produce separate LLM length arguments and a Korean filename ending in [ko] [short].md.
- [ ] Run: pytest tests/test_article_processing.py -q. Expected: failure because process_video applies one global profile and has no metadata scan.
- [ ] Add optional profile to format_output_filename, preserving existing names for omitted/original and appending the non-original profile before the extension.
- [ ] In process_video, resolve profile = config.output.article.resolve_length(lang, article_length) at each language iteration. Pass profile to filename generation and frontmatter formatting.
- [ ] Preserve exact-path skip unless force. When saving article output with dedup enabled, scan storage.article_dir using ArticleIdentity(metadata.id, lang, profile) and the configured recursive flag before transcript/LLM work. On a match, report language/profile/path, return the existing match, and continue.
- [ ] Keep force bypassing both checks, and leave pipe/save_files false behavior unchanged.
- [ ] Run focused tests plus pytest tests/test_youtube_resilience.py -q. Expected: pass.
- [ ] Commit with: git add src/yt/transcript.py src/yt/utils.py tests/test_article_processing.py && git commit -m "feat: deduplicate articles and resolve per-language lengths"

---

### Task 5: Document configuration and complete CLI coverage

**Files:**
- Modify README.md
- Modify src/yt/cli.py
- Modify or create tests/test_cli_config.py

- [ ] Add a test asserting DEFAULT_CONFIG_CONTENT documents length_by_language, dedup, and recursive.
- [ ] Run the focused test and verify it fails before documentation changes.
- [ ] Document the exact YAML configuration and explain fallback length, exact language keys, CLI precedence, article-only frontmatter dedup, recursive scanning, and --force.
- [ ] Do not present subtitle sidecars or manifests as implemented.
- [ ] Run pytest -q. Expected: pass.
- [ ] Commit with: git add README.md src/yt/cli.py tests/test_cli_config.py && git commit -m "docs: document article dedup and language profiles"

---

### Task 6: Final verification and handoff

**Files:** No source changes expected.

- [ ] Run git diff --check and git status --short --branch; confirm no generated article files or metadata artifacts.
- [ ] Run pytest -q and python -m compileall -q src; both must exit 0.
- [ ] Manually verify a matching article with a different date-prefixed filename is skipped; recursive controls nested matches; language profiles generate distinct filenames; CLI --length overrides all languages; --force regenerates; and invalid metadata/dedup configuration fails before processing.
- [ ] If verification finds a defect, add a focused regression test and commit only the specific source/test paths.

## Coverage Check

Task 1 covers configuration, validation, defaults, and precedence. Tasks 2 and 3 cover the enriched frontmatter schema and recursive scanner. Task 4 covers processing order, exact-path/force semantics, profile-aware filenames, and no-network duplicate skips. Task 5 covers user-facing documentation and defaults. Task 6 covers full regression verification. Subtitle sidecar/manifest designs remain deferred as required by the spec.

