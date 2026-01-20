"""OpenAI-compatible LLM translation client."""

import re

import httpx

from yt.utils import get_language_name


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
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
    
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
        
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                self.base_url,
                headers=headers,
                json=payload,
            )
        
        response.raise_for_status()
        result = response.json()
        
        # Extract content from response
        return result["choices"][0]["message"]["content"]
    
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
