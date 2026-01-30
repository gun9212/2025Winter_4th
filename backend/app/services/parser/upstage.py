"""Upstage Document Parser service for converting documents to Markdown."""

import os
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class UpstageParserError(Exception):
    """Exception raised when Upstage parsing fails."""

    pass


class UpstageDocParser:
    """Service for parsing documents using Upstage Document Parse API."""

    API_URL = "https://api.upstage.ai/v1/document-ai/document-parse"

    # Supported file extensions for parsing
    SUPPORTED_EXTENSIONS: set[str] = {
        ".pdf",
        ".docx",
        ".doc",
        ".pptx",
        ".ppt",
        ".xlsx",
        ".xls",
        ".hwp",
        ".hwpx",
        ".txt",
        ".csv",
        ".jpg",
        ".jpeg",
        ".png",
    }

    def __init__(
        self,
        raw_data_path: str = "/app/data/raw",
        processed_data_path: str = "/app/data/processed",
    ) -> None:
        """
        Initialize Upstage parser.

        Args:
            raw_data_path: Path to raw synced files.
            processed_data_path: Path to save parsed markdown files.
        """
        self.api_key = settings.UPSTAGE_API_KEY
        self.raw_data_path = Path(raw_data_path)
        self.processed_data_path = Path(processed_data_path)

        # Ensure processed directory exists
        self.processed_data_path.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning("UPSTAGE_API_KEY is not set")

    def is_supported(self, file_path: str | Path) -> bool:
        """Check if file extension is supported for parsing."""
        ext = Path(file_path).suffix.lower()
        return ext in self.SUPPORTED_EXTENSIONS

    async def parse_document(
        self,
        file_content: bytes,
        filename: str,
        output_format: str = "markdown",
    ) -> dict[str, Any]:
        """
        Parse a document using Upstage API.

        Args:
            file_content: Document content as bytes.
            filename: Original filename.
            output_format: Output format ("html" or "markdown").

        Returns:
            Parsed document result with content and metadata.

        Raises:
            UpstageParserError: If parsing fails.
        """
        if not self.api_key:
            raise UpstageParserError("UPSTAGE_API_KEY is not configured")

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"document": (filename, file_content)},
                    data={"output_format": output_format},
                )

                if response.status_code == 401:
                    raise UpstageParserError("Invalid UPSTAGE_API_KEY")
                elif response.status_code == 413:
                    raise UpstageParserError(f"File too large: {filename}")
                elif response.status_code == 415:
                    raise UpstageParserError(f"Unsupported file type: {filename}")
                elif response.status_code == 429:
                    raise UpstageParserError("Rate limit exceeded")

                response.raise_for_status()

            result = response.json()
            logger.info("Document parsed successfully", filename=filename)
            return result

        except httpx.TimeoutException:
            raise UpstageParserError(f"Parsing timeout for {filename}")
        except httpx.HTTPStatusError as e:
            raise UpstageParserError(f"HTTP error {e.response.status_code}: {str(e)}")
        except Exception as e:
            raise UpstageParserError(f"Parsing failed for {filename}: {str(e)}")

    async def parse_file(
        self,
        file_path: str | Path,
        output_format: str = "markdown",
    ) -> dict[str, Any]:
        """
        Parse a document from a file path.

        Args:
            file_path: Path to the document file.
            output_format: Output format ("html" or "markdown").

        Returns:
            Parsed document result.

        Raises:
            UpstageParserError: If file not found or parsing fails.
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise UpstageParserError(f"File not found: {file_path}")

        if not self.is_supported(file_path):
            raise UpstageParserError(f"Unsupported file type: {file_path.suffix}")

        with open(file_path, "rb") as f:
            content = f.read()

        return await self.parse_document(content, file_path.name, output_format)

    async def parse_and_save(
        self,
        file_path: str | Path,
        output_format: str = "markdown",
    ) -> dict[str, Any]:
        """
        Parse a document and save the result to processed directory.

        Args:
            file_path: Path to the document file (relative to raw_data_path or absolute).
            output_format: Output format.

        Returns:
            Dictionary with parsing result and saved file info.
        """
        file_path = Path(file_path)

        # Handle relative paths
        if not file_path.is_absolute():
            file_path = self.raw_data_path / file_path

        # Parse document
        parse_result = await self.parse_file(file_path, output_format)

        # Extract content
        content = self.get_text_content(parse_result)

        # Calculate relative path for output
        try:
            relative_path = file_path.relative_to(self.raw_data_path)
        except ValueError:
            relative_path = Path(file_path.name)

        # Create output path with .md extension
        output_filename = relative_path.stem + ".md"
        output_path = self.processed_data_path / relative_path.parent / output_filename

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save markdown content
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(
            "Parsed content saved",
            input_file=str(file_path),
            output_file=str(output_path),
        )

        return {
            "success": True,
            "input_path": str(file_path),
            "output_path": str(output_path),
            "content": content,
            "content_length": len(content),
            "images": self.extract_images(parse_result),
            "parse_result": parse_result,
        }

    def get_text_content(self, parse_result: dict[str, Any]) -> str:
        """
        Extract text content from parsed result.

        Args:
            parse_result: Result from parse_document.

        Returns:
            Extracted text content as string.
        """
        # Upstage API returns content in different formats
        content = parse_result.get("content", "")

        if isinstance(content, str):
            return content

        # Handle structured content
        if isinstance(content, dict):
            # Try different possible keys
            for key in ["text", "markdown", "html"]:
                if key in content:
                    return content[key]

        # Fallback: concatenate elements
        elements = parse_result.get("elements", [])
        if elements:
            texts = []
            for elem in elements:
                if elem.get("type") in ("text", "paragraph", "heading"):
                    texts.append(elem.get("content", ""))
            return "\n\n".join(texts)

        return str(content) if content else ""

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
                images.append({
                    "id": element.get("id"),
                    "base64": element.get("content"),
                    "bounding_box": element.get("bounding_box"),
                    "page": element.get("page"),
                })

        return images

    async def parse_directory(
        self,
        directory: str | Path | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """
        Parse all supported documents in a directory.

        Args:
            directory: Directory to parse (defaults to raw_data_path).
            recursive: Whether to process subdirectories.

        Returns:
            Summary of parsing results.
        """
        directory = Path(directory) if directory else self.raw_data_path

        if not directory.exists():
            raise UpstageParserError(f"Directory not found: {directory}")

        results = {
            "success": [],
            "failed": [],
            "skipped": [],
        }

        # Get all files
        pattern = "**/*" if recursive else "*"
        for file_path in directory.glob(pattern):
            if not file_path.is_file():
                continue

            if not self.is_supported(file_path):
                results["skipped"].append({
                    "path": str(file_path),
                    "reason": "Unsupported file type",
                })
                continue

            try:
                result = await self.parse_and_save(file_path)
                results["success"].append({
                    "input": str(file_path),
                    "output": result["output_path"],
                    "content_length": result["content_length"],
                })
            except UpstageParserError as e:
                results["failed"].append({
                    "path": str(file_path),
                    "error": str(e),
                })
                logger.error("Failed to parse file", path=str(file_path), error=str(e))

        logger.info(
            "Directory parsing completed",
            success_count=len(results["success"]),
            failed_count=len(results["failed"]),
            skipped_count=len(results["skipped"]),
        )

        return results


# Singleton instance
upstage_parser = UpstageDocParser()
