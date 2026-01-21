"""OpenAI-compatible LLM translation client."""

import re
import time

import httpx

from yt.utils import get_language_name


class TranslationError(Exception):
    """Raised when translation fails."""
    pass


class TranslationClient:
    """
    Generic OpenAI-compatible chat client for translation.
    
    Works with:
    - OpenAI
    - OpenRouter
    - Ollama
    - Any OpenAI-compatible chat completions endpoint
    """
    
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o",
        timeout: float = 120.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
    
    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        preserve_formatting: bool = True,
    ) -> str:
        """
        Translate text from source language to target language.
        
        Args:
            text: Text to translate
            source_language: Source language code (e.g., 'en', 'ja')
            target_language: Target language code
            preserve_formatting: Whether to preserve timestamps and formatting
        
        Returns:
            Translated text
        """
        source_name = get_language_name(source_language)
        target_name = get_language_name(target_language)
        
        if preserve_formatting:
            system_prompt = f"""You are a professional translator. Translate the following subtitle content from {source_name} to {target_name}.

IMPORTANT RULES:
1. Preserve ALL timestamp formatting exactly as-is (e.g., "00:01:23,456 --> 00:01:25,789" or "00:01:23.456 --> 00:01:25.789")
2. Preserve subtitle numbering if present
3. Preserve line breaks within subtitle entries
4. Only translate the actual dialogue/text content
5. Maintain the same structure and format of the original
6. Do not add any explanations or notes
7. Output ONLY the translated content, nothing else"""
        else:
            system_prompt = f"""You are a professional translator. Translate the following text from {source_name} to {target_name}.

IMPORTANT RULES:
1. Provide a natural, fluent translation
2. Maintain paragraph breaks if present
3. Do not add any explanations or notes
4. Output ONLY the translated content, nothing else"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,  # Lower temperature for more consistent translations
        }
        
        last_error: TranslationError | None = None
        
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        self.base_url,
                        headers=headers,
                        json=payload,
                    )
                
                response.raise_for_status()
                result = response.json()
                
                # Check for content moderation / refusal
                choice = result.get("choices", [{}])[0]
                finish_reason = choice.get("finish_reason", "")
                
                if finish_reason == "content_filter":
                    raise TranslationError("LLM rejected content due to content policy")
                
                content = choice.get("message", {}).get("content", "")
                
                if not content:
                    raise TranslationError("LLM returned empty response")
                
                # Check for common refusal patterns
                refusal_patterns = [
                    "I cannot",
                    "I'm not able to",
                    "I apologize, but I cannot",
                    "I'm sorry, but I can't",
                    "As an AI",
                ]
                content_start = content[:100].strip()
                if any(pattern.lower() in content_start.lower() for pattern in refusal_patterns):
                    raise TranslationError(f"LLM refused to process content: {content_start}...")
                
                return content
            except httpx.TimeoutException as e:
                last_error = TranslationError(f"Translation request timed out after {self.timeout}s")
                last_error.__cause__ = e
            except httpx.HTTPStatusError as e:
                # Extract error message from response if possible
                try:
                    error_detail = e.response.json().get("error", {}).get("message", str(e))
                except Exception:
                    error_detail = str(e)
                last_error = TranslationError(f"Translation API error ({e.response.status_code}): {error_detail}")
                last_error.__cause__ = e
                # Don't retry on client errors, except for:
                # - 429 (rate limit)
                # - 400/401/502/503 with "provider" in error message (OpenRouter transient errors)
                is_provider_error = "provider" in error_detail.lower()
                is_retryable_status = e.response.status_code in (429, 502, 503)
                if 400 <= e.response.status_code < 500 and not is_retryable_status and not is_provider_error:
                    raise last_error
            except TranslationError as e:
                last_error = e
            except Exception as e:
                last_error = TranslationError(f"Translation failed: {e}")
                last_error.__cause__ = e
            
            # Wait before retrying (exponential backoff: 2s, 4s, 8s, ...)
            if attempt < self.max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                time.sleep(wait_time)
        
        # All retries exhausted
        raise last_error if last_error else TranslationError("Translation failed after retries")
    
    def translate_srt(
        self,
        srt_content: str,
        source_language: str,
        target_language: str,
    ) -> str:
        """
        Translate SRT subtitle content, preserving formatting.
        
        For large files, splits into chunks to avoid token limits.
        """
        # Check if content is small enough to translate in one go
        if len(srt_content) < 15000:  # Roughly 4k tokens
            return self.translate(
                srt_content, source_language, target_language, preserve_formatting=True
            )
        
        # Split into chunks by subtitle entries and translate in batches
        return self._translate_chunked(
            srt_content, source_language, target_language, chunk_size=50
        )
    
    def translate_vtt(
        self,
        vtt_content: str,
        source_language: str,
        target_language: str,
    ) -> str:
        """
        Translate VTT subtitle content, preserving formatting.
        """
        # Check if content is small enough
        if len(vtt_content) < 15000:
            return self.translate(
                vtt_content, source_language, target_language, preserve_formatting=True
            )
        
        return self._translate_chunked(
            vtt_content, source_language, target_language, chunk_size=50
        )
    
    def translate_plain_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        """Translate plain text without subtitle formatting."""
        return self.translate(
            text, source_language, target_language, preserve_formatting=False
        )
    
    def _translate_chunked(
        self,
        content: str,
        source_language: str,
        target_language: str,
        chunk_size: int = 50,
    ) -> str:
        """
        Translate content in chunks to handle large files.
        
        Splits by subtitle entries (numbered blocks) and translates in batches.
        """
        # Split SRT/VTT into entries
        # Pattern matches subtitle blocks (number + timestamp + text)
        entries = re.split(r'\n\n+', content.strip())
        
        # Check if it's VTT (starts with WEBVTT)
        header = ""
        if entries and entries[0].strip().startswith("WEBVTT"):
            header = entries[0] + "\n\n"
            entries = entries[1:]
        
        translated_parts = [header] if header else []
        
        # Process in chunks
        for i in range(0, len(entries), chunk_size):
            chunk = entries[i:i + chunk_size]
            chunk_text = "\n\n".join(chunk)
            
            translated = self.translate(
                chunk_text,
                source_language,
                target_language,
                preserve_formatting=True,
            )
            translated_parts.append(translated)
        
        return "\n\n".join(translated_parts)
    
    def generate_article(
        self,
        content: str,
        language: str | None = None,
        length: str = "original",
    ) -> str:
        """
        Generate an article from transcript content using LLM.
        
        Args:
            content: Plain text transcript content
            language: Target language (None = infer from content)
            length: Article length - 'original', 'long', 'medium', 'short'
        
        Returns:
            Generated article text
        """
        from importlib.resources import files
        
        # Load prompt template
        prompt_path = files("yt").joinpath("prompt.md")
        prompt_template = prompt_path.read_text()
        
        # Replace length placeholder
        system_prompt = prompt_template.replace("{{length}}", length)
        
        # Add language instruction if specified
        if language:
            language_name = get_language_name(language)
            system_prompt = system_prompt.replace(
                "**Instructions:**",
                f"**Article Specifications:**\n*   [Language]: {language_name}\n\n**Instructions:**"
            )
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0.7,  # Slightly higher for creative writing
        }
        
        try:
            with httpx.Client(timeout=self.timeout * 2) as client:  # Longer timeout for articles
                response = client.post(
                    self.base_url,
                    headers=headers,
                    json=payload,
                )
            
            response.raise_for_status()
            result = response.json()
            
            # Check for content moderation / refusal
            choice = result.get("choices", [{}])[0]
            finish_reason = choice.get("finish_reason", "")
            
            if finish_reason == "content_filter":
                raise TranslationError("LLM rejected content due to content policy")
            
            content = choice.get("message", {}).get("content", "")
            
            if not content:
                raise TranslationError("LLM returned empty response for article")
            
            # Check for common refusal patterns
            refusal_patterns = [
                "I cannot",
                "I'm not able to",
                "I apologize, but I cannot",
                "I'm sorry, but I can't",
                "As an AI",
            ]
            content_start = content[:100].strip()
            if any(pattern.lower() in content_start.lower() for pattern in refusal_patterns):
                raise TranslationError(f"LLM refused to generate article: {content_start}...")
            
            return content
        except httpx.TimeoutException as e:
            raise TranslationError(f"Article generation timed out after {self.timeout * 2}s") from e
        except httpx.HTTPStatusError as e:
            try:
                error_detail = e.response.json().get("error", {}).get("message", str(e))
            except Exception:
                error_detail = str(e)
            raise TranslationError(f"Article generation API error ({e.response.status_code}): {error_detail}") from e
        except TranslationError:
            raise  # Re-raise TranslationError as-is
        except Exception as e:
            raise TranslationError(f"Article generation failed: {e}") from e
