"""Upstage Document Parser service for converting documents to Markdown/HTML."""

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
    """Service for parsing documents using Upstage Document Parse API (RAG Optimized)."""

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
        """
        Initialize Upstage parser.

        Args:
            raw_data_path: Path to raw data directory.
            processed_data_path: Path to processed data directory.
        """
        self.api_key = settings.UPSTAGE_API_KEY
        self.raw_data_path = Path(raw_data_path)
        self.processed_data_path = Path(processed_data_path)

        # Ensure processed directory exists
        self.processed_data_path.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning("UPSTAGE_API_KEY is not set")

    async def _call_api(
        self,
        file_path: Path,
        output_format: str,
    ) -> str:
        """
        Call Upstage Document Parse API with specified output format.

        Args:
            file_path: Path to the document file.
            output_format: "markdown" or "html".

        Returns:
            Parsed content string.
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=180.0) as client:
            with open(file_path, "rb") as f:
                response = await client.post(
                    self.API_URL,
                    headers=headers,
                    files={"document": f},
                    data={"output_format": output_format},
                )

        if response.status_code != 200:
            logger.error(
                "[PARSER] API request failed",
                status_code=response.status_code,
                output_format=output_format,
                response_text=response.text[:500],
            )
            raise UpstageParserError(
                f"API Error {response.status_code}: {response.text}"
            )

        result = response.json()
        content = result.get("content")

        if not content:
            logger.error(
                "[PARSER] Empty content from API",
                output_format=output_format,
                response_keys=list(result.keys()),
            )
            raise UpstageParserError(
                f"API 응답에서 {output_format} content를 추출할 수 없습니다."
            )

        return content

    async def parse_and_save(
        self,
        file_path: str | Path,
    ) -> dict[str, Any]:
        """
        Parse a document and save both Markdown and HTML results.

        Args:
            file_path: Path to the document file.

        Returns:
            Dictionary with parsing results including both contents and output paths.

        Raises:
            UpstageParserError: If parsing fails.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise UpstageParserError(f"File not found: {file_path}")

        # 출력 경로 계산 (raw 폴더 구조 유지)
        try:
            relative_path = file_path.relative_to(self.raw_data_path)
        except ValueError:
            relative_path = Path(file_path.name)

        output_dir = self.processed_data_path / relative_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # 파일명 (확장자 제외)
        base_name = relative_path.stem
        md_output_path = output_dir / f"{base_name}.md"
        html_output_path = output_dir / f"{base_name}.html"

        logger.info(
            "[PARSER] Starting document parse (markdown + html)",
            input_file=str(file_path),
            md_output=str(md_output_path),
            html_output=str(html_output_path),
        )

        try:
            # 1. Markdown 요청
            logger.info("[PARSER] Fetching markdown format...")
            markdown_content = await self._call_api(file_path, "markdown")

            # 2. HTML 요청
            logger.info("[PARSER] Fetching html format...")
            html_content = await self._call_api(file_path, "html")

            # 3. Markdown 저장
            async with aiofiles.open(md_output_path, "w", encoding="utf-8") as f:
                await f.write(markdown_content)

            # 4. HTML 저장
            async with aiofiles.open(html_output_path, "w", encoding="utf-8") as f:
                await f.write(html_content)

            logger.info(
                "[PARSER] Document parsed successfully (both formats)",
                input_file=str(file_path),
                md_length=len(markdown_content),
                html_length=len(html_content),
            )

            return {
                "success": True,
                "input_path": str(file_path),
                "output_path": str(md_output_path),  # 기본은 markdown 경로
                "html_output_path": str(html_output_path),
                "content": markdown_content,  # DB에는 markdown 저장
                "html_content": html_content,
                "content_length": len(markdown_content),
                "html_length": len(html_content),
                "images": [],
            }

        except UpstageParserError:
            raise
        except Exception as e:
            logger.error(
                "[PARSER] Parsing failed",
                error=str(e),
                file=str(file_path),
            )
            raise UpstageParserError(str(e))
