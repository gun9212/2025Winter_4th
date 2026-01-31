"""Upstage Document Parser service for converting documents to Markdown."""

from pathlib import Path
from typing import Any

import aiofiles
import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class UpstageParserError(Exception):
    """Exception raised when Upstage parsing fails."""

    pass


class UpstageDocParser:
    """Service for parsing documents using Upstage Document Parse API."""

    # Document Parse API endpoint
    API_URL = "https://api.upstage.ai/v1/document-ai/document-parse"

    # Supported file extensions for parsing
    SUPPORTED_EXTENSIONS: set[str] = {
        ".pdf", ".docx", ".doc", ".pptx", ".ppt",
        ".xlsx", ".xls", ".hwp", ".hwpx",
        ".txt", ".csv", ".jpg", ".jpeg", ".png",
    }

    def __init__(
        self,
        raw_data_path: str = "/app/data/raw",
        processed_data_path: str = "/app/data/processed",
    ) -> None:
        """Initialize Upstage parser."""
        self.api_key = settings.UPSTAGE_API_KEY
        self.raw_data_path = Path(raw_data_path)
        self.processed_data_path = Path(processed_data_path)

        self.processed_data_path.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning("UPSTAGE_API_KEY is not set")

    def _extract_text_content(self, content: Any) -> str:
        """
        Extract text string from API response content.

        Handles cases where content might be dict, list, or string.

        Args:
            content: Raw content from API response.

        Returns:
            Extracted text as string.

        Raises:
            UpstageParserError: If content cannot be extracted.
        """
        # Case 1: Already a string
        if isinstance(content, str):
            return content

        # Case 2: Dictionary - try common keys
        if isinstance(content, dict):
            logger.info(
                "[PARSER] Content is dict, extracting text",
                keys=list(content.keys()),
            )
            extracted = (
                content.get("text")
                or content.get("markdown")
                or content.get("html")
                or content.get("content")
            )
            if extracted:
                # Recursive call in case nested
                return self._extract_text_content(extracted)
            # Fallback: convert dict to string
            import json
            return json.dumps(content, ensure_ascii=False, indent=2)

        # Case 3: List - join elements
        if isinstance(content, list):
            logger.info("[PARSER] Content is list, joining elements")
            texts = [self._extract_text_content(item) for item in content]
            return "\n".join(texts)

        # Case 4: Other types - convert to string
        return str(content)

    async def parse_and_save(
        self,
        file_path: str | Path,
    ) -> dict[str, Any]:
        """
        Parse a document and save the Markdown result.

        Args:
            file_path: Path to the document file.

        Returns:
            Dictionary with parsing results.

        Raises:
            UpstageParserError: If parsing fails.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise UpstageParserError(f"File not found: {file_path}")

        # Calculate output path
        try:
            relative_path = file_path.relative_to(self.raw_data_path)
        except ValueError:
            relative_path = Path(file_path.name)

        output_dir = self.processed_data_path / relative_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / f"{relative_path.stem}.md"

        logger.info(
            "[PARSER] Starting document parse",
            input_file=str(file_path),
            output_file=str(output_path),
        )

        try:
            # 1. API 호출
            headers = {"Authorization": f"Bearer {self.api_key}"}

            async with httpx.AsyncClient(timeout=180.0) as client:
                with open(file_path, "rb") as f:
                    response = await client.post(
                        self.API_URL,
                        headers=headers,
                        files={"document": f},
                        data={"output_format": "markdown"},
                    )

            # 2. 응답 검증
            if response.status_code != 200:
                logger.error(
                    "[PARSER] API request failed",
                    status_code=response.status_code,
                    response_text=response.text[:500],
                )
                raise UpstageParserError(
                    f"API Error {response.status_code}: {response.text}"
                )

            result = response.json()

            logger.info(
                "[PARSER] API response received",
                response_type=type(result).__name__,
                response_keys=list(result.keys()) if isinstance(result, dict) else None,
            )

            # 3. Content 추출 (타입 방어 로직 포함)
            raw_content = result.get("content") if isinstance(result, dict) else result

            if not raw_content:
                logger.error(
                    "[PARSER] Empty content from API",
                    result_keys=list(result.keys()) if isinstance(result, dict) else None,
                )
                raise UpstageParserError("API 응답에서 content를 추출할 수 없습니다.")

            # 4. 문자열로 변환 (핵심 버그 수정)
            content = self._extract_text_content(raw_content)

            if not content or not content.strip():
                raise UpstageParserError("추출된 content가 비어있습니다.")

            logger.info(
                "[PARSER] Content extracted",
                content_type=type(content).__name__,
                content_length=len(content),
            )

            # 5. 파일 저장
            async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(
                "[PARSER] Document parsed successfully",
                input_file=str(file_path),
                output_file=str(output_path),
                content_length=len(content),
            )

            return {
                "success": True,
                "input_path": str(file_path),
                "output_path": str(output_path),
                "content": content,
                "content_length": len(content),
                "images": [],
            }

        except UpstageParserError:
            raise
        except Exception as e:
            logger.error(
                "[PARSER] Parsing failed",
                error=str(e),
                error_type=type(e).__name__,
                file=str(file_path),
            )
            raise UpstageParserError(str(e))
