"""Upstage Document Parser service."""

import httpx
from typing import Any

from app.core.config import settings


class UpstageDocParser:
    """Service for parsing documents using Upstage Document Parse API."""

    API_URL = "https://api.upstage.ai/v1/document-ai/document-parse"

    def __init__(self) -> None:
        self.api_key = settings.UPSTAGE_API_KEY

    async def parse_document(
        self,
        file_content: bytes,
        filename: str,
        output_format: str = "html",
    ) -> dict[str, Any]:
        """
        Parse a document using Upstage API.

        Args:
            file_content: Document content as bytes.
            filename: Original filename.
            output_format: Output format ("html" or "markdown").

        Returns:
            Parsed document result with content and images.
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                files={"document": (filename, file_content)},
                data={"output_format": output_format},
            )
            response.raise_for_status()

        return response.json()

    async def parse_file(
        self,
        file_path: str,
        output_format: str = "html",
    ) -> dict[str, Any]:
        """
        Parse a document from a file path.

        Args:
            file_path: Path to the document file.
            output_format: Output format.

        Returns:
            Parsed document result.
        """
        import os

        with open(file_path, "rb") as f:
            content = f.read()

        filename = os.path.basename(file_path)
        return await self.parse_document(content, filename, output_format)

    def extract_images(self, parse_result: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract images from parsed document result.

        Args:
            parse_result: Result from parse_document.

        Returns:
            List of image info dictionaries.
        """
        images = []

        for element in parse_result.get("elements", []):
            if element.get("type") == "image":
                images.append(
                    {
                        "id": element.get("id"),
                        "base64": element.get("content"),
                        "bounding_box": element.get("bounding_box"),
                        "page": element.get("page"),
                    }
                )

        return images

    def get_text_content(self, parse_result: dict[str, Any]) -> str:
        """
        Extract text content from parsed result.

        Args:
            parse_result: Result from parse_document.

        Returns:
            Extracted text content.
        """
        content = parse_result.get("content", {})

        if isinstance(content, str):
            return content

        # Handle structured content
        if isinstance(content, dict):
            return content.get("text", "") or content.get("html", "")

        return ""
