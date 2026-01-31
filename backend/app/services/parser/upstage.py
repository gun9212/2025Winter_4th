"""Upstage Document Parser service for converting documents to Markdown/HTML."""

import os
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

    # 테스트에서 성공한 Layout Analysis 엔드포인트 사용
    API_URL = "https://api.upstage.ai/v1/document-ai/layout-analysis"

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
        """
        self.api_key = settings.UPSTAGE_API_KEY
        self.raw_data_path = Path(raw_data_path)
        self.processed_data_path = Path(processed_data_path)

        # Ensure processed directory exists
        self.processed_data_path.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning("UPSTAGE_API_KEY is not set")

    async def parse_and_save(
        self,
        file_path: str | Path,
    ) -> dict[str, Any]:
        """
        Parse a document and save the result to processed directory.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise UpstageParserError(f"File not found: {file_path}")

        # 출력 경로 계산 (raw 폴더 구조 유지)
        try:
            relative_path = file_path.relative_to(self.raw_data_path)
        except ValueError:
            # raw_data_path 외부에 있는 경우 파일명만 사용
            relative_path = Path(file_path.name)

        output_dir = self.processed_data_path / relative_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 확장자를 .md로 변경하여 저장 경로 설정
        output_filename = relative_path.with_suffix('.md').name
        output_path = output_dir / output_filename

        try:
            # 1. API 호출 (비동기)
            headers = {"Authorization": f"Bearer {self.api_key}"}
            
            async with httpx.AsyncClient(timeout=180.0) as client:
                # 대용량 파일 처리를 위해 비동기 파일 읽기 대신 동기 오픈 후 스트림 전송
                # (httpx files 파라미터는 바이너리 객체를 요구함)
                with open(file_path, "rb") as f:
                    response = await client.post(
                        self.API_URL,
                        headers=headers,
                        files={"document": f},
                        data={"output_format": "html"} # HTML 요청 (Upstage가 가장 잘함)
                    )
            
            if response.status_code != 200:
                raise UpstageParserError(f"API Error {response.status_code}: {response.text}")

            result = response.json()

            # 2. [핵심 수정] 데이터 추출 로직 개선
            # API 응답의 Root Level에서 키를 찾아야 함
            content = result.get("html")
            
            if not content:
                content = result.get("markdown")
            
            if not content:
                content = result.get("text")
                
            # 만약 content 키 안에 숨어있는 경우 (구버전 대응)
            if not content and "content" in result:
                inner = result["content"]
                if isinstance(inner, dict):
                    content = inner.get("html") or inner.get("markdown") or inner.get("text")
                elif isinstance(inner, str):
                    content = inner

            if not content:
                logger.error("Empty content from Upstage", response_keys=list(result.keys()))
                raise UpstageParserError("API 응답에서 텍스트를 추출할 수 없습니다.")

            # 3. 결과 저장 (aiofiles 사용)
            async with aiofiles.open(output_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.info(
                "Parsed content saved",
                input_file=str(file_path),
                output_file=str(output_path),
                length=len(content)
            )

            return {
                "success": True,
                "input_path": str(file_path),
                "output_path": str(output_path),
                "content": content, # 이 값이 DB로 들어감
                "content_length": len(content),
                "images": [], # 필요 시 elements에서 추출 가능
            }

        except Exception as e:
            logger.error("Upstage parsing failed", error=str(e), file=str(file_path))
            raise UpstageParserError(str(e))