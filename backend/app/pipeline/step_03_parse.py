"""Step 3: Parsing - Parse documents using Upstage API with Gemini Vision enhancement.

This module handles document parsing:
1. Upstage Document Parse API for Markdown conversion
2. Coordinate-based image cropping from PDF pages
3. Gemini 2.0 Flash Vision for table and image captioning
4. Caption injection into Markdown content

Output: Markdown content with captions injected for images/tables.
"""

import base64
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
from PIL import Image

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class ParsedElement:
    """A parsed element from the document."""
    
    element_id: str
    element_type: str  # text, table, image, header
    content: str
    page: int | None = None
    bounding_box: dict | None = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class ParsingResult:
    """Result of document parsing."""
    
    html_content: str
    markdown_content: str
    elements: list[ParsedElement]
    images: list[dict]
    tables: list[dict]
    text_content: str
    total_pages: int
    metadata: dict


class ParsingService:
    """
    Service for parsing documents using Upstage API with Gemini Vision enhancement.
    
    Workflow:
        1. Send document to Upstage API → HTML + elements with coordinates
        2. Extract images/tables using coordinates from original PDF
        3. Send extracted images to Gemini 2.0 Flash for captioning
        4. Replace <img> tags with text descriptions for better RAG
    """

    UPSTAGE_API_URL = "https://api.upstage.ai/v1/document-ai/document-parse"

    def __init__(self):
        """Initialize parsing service."""
        self.upstage_api_key = settings.UPSTAGE_API_KEY
        self.gemini_model = None  # Lazy initialization

    def _get_gemini_model(self):
        """Lazy initialization of Gemini model."""
        if self.gemini_model is None:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self.gemini_model = genai.GenerativeModel(settings.GEMINI_MODEL)
        return self.gemini_model

    def _extract_text_content(self, content: Any) -> str:
        """
        Extract text string from API response content.
        
        Merged from teammate's upstage.py - handles cases where content 
        might be dict, list, or string (defensive parsing).
        
        Args:
            content: Raw content from API response.
        
        Returns:
            Extracted text as string.
        """
        import json
        
        # Case 1: Already a string
        if isinstance(content, str):
            return content

        # Case 2: Dictionary - try common keys
        if isinstance(content, dict):
            logger.debug(
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
            return json.dumps(content, ensure_ascii=False, indent=2)

        # Case 3: List - join elements
        if isinstance(content, list):
            logger.debug("[PARSER] Content is list, joining elements")
            texts = [self._extract_text_content(item) for item in content]
            return "\n".join(texts)

        # Case 4: Other types - convert to string
        return str(content)

    async def parse_document(
        self,
        file_content: bytes,
        filename: str,
        output_format: str = "markdown",  # Changed: Markdown 출력 중심
        extract_images: bool = True,
        caption_images: bool = True,
    ) -> ParsingResult:
        """
        Parse a document using Upstage API.
        
        Args:
            file_content: Document content as bytes
            filename: Original filename
            output_format: Output format ("html" or "markdown")
            extract_images: Whether to extract images
            caption_images: Whether to generate image/table captions with Gemini
            
        Returns:
            ParsingResult with parsed content and elements
        """
        # Step 1: Call Upstage API
        upstage_result = await self._call_upstage_api(
            file_content, filename, output_format
        )

        # Extract basic content using defensive parsing
        content = upstage_result.get("content", {})
        
        # Try to extract content from different possible response structures
        if isinstance(content, dict):
            # If content is a dict, try to get html/markdown/text keys
            html_content = content.get("html", "")
            markdown_content = content.get("markdown", "")
            text_content = content.get("text", "")
            
            # If all empty, use _extract_text_content as fallback
            if not (html_content or markdown_content or text_content):
                extracted = self._extract_text_content(content)
                # If we got extracted text, use it for all fields
                if extracted:
                    html_content = extracted
                    markdown_content = extracted
                    text_content = extracted
        else:
            # If content is not a dict, use _extract_text_content
            extracted = self._extract_text_content(content)
            html_content = extracted
            markdown_content = extracted
            text_content = extracted
        
        logger.debug(
            "[PARSER] Content extracted",
            html_len=len(html_content),
            markdown_len=len(markdown_content),
            text_len=len(text_content),
        )

        # Step 2: Process elements
        elements = []
        images = []
        tables = []
        
        for elem in upstage_result.get("elements", []):
            parsed_elem = ParsedElement(
                element_id=elem.get("id", ""),
                element_type=elem.get("type", "text"),
                content=elem.get("content", ""),
                page=elem.get("page"),
                bounding_box=elem.get("bounding_box") or elem.get("coordinates"),
                metadata=elem.get("metadata", {}),
            )
            elements.append(parsed_elem)
            
            if elem.get("type") == "image":
                images.append({
                    "id": elem.get("id"),
                    "base64": elem.get("content"),
                    "bounding_box": elem.get("bounding_box") or elem.get("coordinates"),
                    "page": elem.get("page"),
                })
            elif elem.get("type") == "table":
                tables.append({
                    "id": elem.get("id"),
                    "content": elem.get("content"),
                    "bounding_box": elem.get("bounding_box") or elem.get("coordinates"),
                    "page": elem.get("page"),
                })

        # Step 3: Caption images and tables with Gemini if requested
        # Now works with Markdown content instead of HTML
        if caption_images and (images or tables):
            markdown_content = await self._enhance_with_captions_markdown(
                markdown_content,
                file_content,
                filename,
                images,
                tables,
            )

        return ParsingResult(
            html_content=html_content,
            markdown_content=markdown_content,
            elements=elements,
            images=images,
            tables=tables,
            text_content=text_content,
            total_pages=upstage_result.get("metadata", {}).get("total_pages", 1),
            metadata=upstage_result.get("metadata", {}),
        )

    async def _call_upstage_api(
        self,
        file_content: bytes,
        filename: str,
        output_format: str,
    ) -> dict[str, Any]:
        """
        Call Upstage Document Parse API.
        
        Args:
            file_content: Document content as bytes
            filename: Original filename
            output_format: Output format
            
        Returns:
            API response dictionary
        """
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                self.UPSTAGE_API_URL,
                headers={"Authorization": f"Bearer {self.upstage_api_key}"},
                files={"document": (filename, file_content)},
                data={
                    "output_format": output_format,
                    "coordinates": "true",  # Request coordinates for cropping
                },
            )
            response.raise_for_status()
            return response.json()

    async def _enhance_with_captions(
        self,
        html_content: str,
        original_file: bytes,
        filename: str,
        images: list[dict],
        tables: list[dict],
    ) -> str:
        """
        Enhance HTML content by replacing images/tables with Gemini-generated captions.
        
        Uses coordinates to crop high-resolution images from original PDF
        before sending to Gemini for better accuracy.
        
        Args:
            html_content: Original HTML from Upstage
            original_file: Original file bytes (for PDF cropping)
            filename: Original filename
            images: List of image dictionaries
            tables: List of table dictionaries
            
        Returns:
            Enhanced HTML with text descriptions replacing images
        """
        # Process images
        for img in images:
            try:
                caption = await self._caption_image(
                    img, original_file, filename, is_table=False
                )
                if caption:
                    # Replace image tag with caption text
                    img_id = img.get("id", "")
                    html_content = self._replace_element_with_caption(
                        html_content, img_id, caption, "image"
                    )
            except Exception as e:
                logger.warning("Image captioning failed", image_id=img.get("id"), error=str(e))

        # Process tables
        for table in tables:
            try:
                # For tables, try to convert to Markdown format
                caption = await self._caption_image(
                    table, original_file, filename, is_table=True
                )
                if caption:
                    table_id = table.get("id", "")
                    html_content = self._replace_element_with_caption(
                        html_content, table_id, caption, "table"
                    )
            except Exception as e:
                logger.warning("Table captioning failed", table_id=table.get("id"), error=str(e))

        return html_content

    async def _caption_image(
        self,
        element: dict,
        original_file: bytes,
        filename: str,
        is_table: bool = False,
    ) -> str | None:
        """
        Generate caption for an image or table using Gemini 2.0 Flash Vision.
        
        For PDFs, uses coordinate-based cropping for higher quality.
        
        Args:
            element: Element dictionary with base64 or bounding_box
            original_file: Original file bytes
            filename: Original filename
            is_table: Whether this is a table (affects prompt)
            
        Returns:
            Generated caption or Markdown (for tables)
        """
        import google.generativeai as genai
        
        model = self._get_gemini_model()
        
        # Try to get image from element base64 first
        image_data = None
        if element.get("base64"):
            image_data = base64.b64decode(element["base64"])
        
        # If PDF and we have coordinates, try to crop from original
        if filename.lower().endswith(".pdf") and element.get("bounding_box"):
            cropped = await self._crop_from_pdf(
                original_file, 
                element["page"],
                element["bounding_box"],
            )
            if cropped:
                image_data = cropped

        if not image_data:
            return None

        # Create prompt based on element type
        if is_table:
            prompt = """이 이미지는 학생회 회의 자료의 표입니다.
표의 내용을 Markdown 테이블 형식으로 정확하게 변환해주세요.
헤더와 데이터를 구분하고, 모든 셀의 내용을 포함해주세요.

예시:
| 항목 | 예산 | 집행 |
|------|------|------|
| 간식비 | 500,000 | 450,000 |

표를 Markdown으로 변환한 결과만 출력하세요."""
        else:
            prompt = """이 이미지는 학생회 문서의 일부입니다.
이미지가 표나 조직도라면 내용을 텍스트로 상세히 설명해주세요.
일반 사진이나 그래프라면 그 상황과 의미를 상세히 묘사해주세요.

이미지의 내용을 설명하는 텍스트만 출력하세요."""

        try:
            # Convert to PIL Image for Gemini
            image = Image.open(io.BytesIO(image_data))
            
            response = await model.generate_content_async([prompt, image])
            return response.text.strip()
            
        except Exception as e:
            logger.error("Gemini Vision failed", error=str(e))
            return None

    async def _crop_from_pdf(
        self,
        pdf_bytes: bytes,
        page_num: int | None,
        bounding_box: dict,
    ) -> bytes | None:
        """
        Crop a region from a PDF page using coordinates.
        
        Uses pdf2image for high-quality rendering.
        
        Args:
            pdf_bytes: PDF file as bytes
            page_num: Page number (1-indexed)
            bounding_box: Bounding box with x1, y1, x2, y2
            
        Returns:
            Cropped image as bytes
        """
        try:
            from pdf2image import convert_from_bytes
            
            # Convert PDF page to image (high DPI for quality)
            images = convert_from_bytes(
                pdf_bytes,
                first_page=page_num or 1,
                last_page=page_num or 1,
                dpi=200,
            )
            
            if not images:
                return None
            
            page_image = images[0]
            
            # Calculate crop coordinates
            # Bounding box format may vary, handle common formats
            if isinstance(bounding_box, dict):
                x1 = bounding_box.get("x1", bounding_box.get("left", 0))
                y1 = bounding_box.get("y1", bounding_box.get("top", 0))
                x2 = bounding_box.get("x2", bounding_box.get("right", page_image.width))
                y2 = bounding_box.get("y2", bounding_box.get("bottom", page_image.height))
            elif isinstance(bounding_box, (list, tuple)) and len(bounding_box) >= 4:
                x1, y1, x2, y2 = bounding_box[:4]
            else:
                return None
            
            # Scale coordinates if needed (Upstage returns normalized 0-1 coords)
            if all(0 <= v <= 1 for v in [x1, y1, x2, y2]):
                x1 = int(x1 * page_image.width)
                y1 = int(y1 * page_image.height)
                x2 = int(x2 * page_image.width)
                y2 = int(y2 * page_image.height)
            else:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            
            # Crop the image
            cropped = page_image.crop((x1, y1, x2, y2))
            
            # Convert to bytes
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            return buffer.getvalue()
            
        except Exception as e:
            logger.warning("PDF cropping failed", error=str(e))
            return None

    def _replace_element_with_caption(
        self,
        html_content: str,
        element_id: str,
        caption: str,
        element_type: str,
    ) -> str:
        """
        Replace an element in HTML with its text caption.
        
        Args:
            html_content: Original HTML
            element_id: ID of element to replace
            caption: Text caption to insert
            element_type: Type of element (image, table)
            
        Returns:
            Modified HTML
        """
        import re
        
        # Create replacement HTML with caption
        if element_type == "table":
            replacement = f'<div class="table-caption" data-original-id="{element_id}">\n<pre>\n{caption}\n</pre>\n</div>'
        else:
            replacement = f'<div class="image-caption" data-original-id="{element_id}">\n<p>[이미지 설명] {caption}</p>\n</div>'
        
        # Try to find and replace the element by ID
        # Common patterns for image/table elements
        patterns = [
            rf'<img[^>]*id=["\']?{re.escape(element_id)}["\']?[^>]*>',
            rf'<table[^>]*id=["\']?{re.escape(element_id)}["\']?[^>]*>.*?</table>',
            rf'<figure[^>]*id=["\']?{re.escape(element_id)}["\']?[^>]*>.*?</figure>',
        ]
        
        for pattern in patterns:
            html_content = re.sub(pattern, replacement, html_content, flags=re.DOTALL | re.IGNORECASE)
        
        return html_content

    # ========== NEW: Markdown-based caption injection ==========

    async def _enhance_with_captions_markdown(
        self,
        markdown_content: str,
        original_file: bytes,
        filename: str,
        images: list[dict],
        tables: list[dict],
    ) -> str:
        """
        Enhance Markdown content by injecting Gemini-generated captions.
        """
        orphan_captions: list[tuple[str, str, int | None]] = []

        for i, img in enumerate(images):
            try:
                caption = await self._caption_image(img, original_file, filename, is_table=False)
                if caption:
                    result = self._inject_caption_markdown(markdown_content, caption, "image", i)
                    if result["injected"]:
                        markdown_content = result["content"]
                    else:
                        orphan_captions.append((caption, "image", img.get("page")))
            except Exception as e:
                logger.warning("Image captioning failed", image_index=i, error=str(e))

        for i, table in enumerate(tables):
            try:
                caption = await self._caption_image(table, original_file, filename, is_table=True)
                if caption:
                    result = self._inject_caption_markdown(markdown_content, caption, "table", i)
                    if result["injected"]:
                        markdown_content = result["content"]
                    else:
                        orphan_captions.append((caption, "table", table.get("page")))
            except Exception as e:
                logger.warning("Table captioning failed", table_index=i, error=str(e))

        if orphan_captions:
            markdown_content = self._append_orphan_captions(markdown_content, orphan_captions)

        return markdown_content

    def _inject_caption_markdown(
        self,
        content: str,
        caption: str,
        element_type: str,
        element_index: int,
    ) -> dict[str, Any]:
        """Inject caption into Markdown using ![...](...) pattern matching."""
        if element_type == "table":
            formatted_caption = f"\n\n{caption}\n\n"
        else:
            formatted_caption = f"\n\n> **[이미지 설명]** {caption}\n\n"

        image_pattern = r'!\[[^\]]*\]\([^)]*\)'
        matches = list(re.finditer(image_pattern, content))
        
        if matches and element_index < len(matches):
            match = matches[element_index]
            new_content = content[:match.end()] + formatted_caption + content[match.end():]
            return {"content": new_content, "injected": True, "method": "pattern_match"}

        placeholder_pattern = r'!\[image\]\(/image/placeholder\)'
        placeholder_matches = list(re.finditer(placeholder_pattern, content))
        
        if placeholder_matches and element_index < len(placeholder_matches):
            match = placeholder_matches[element_index]
            new_content = content[:match.end()] + formatted_caption + content[match.end():]
            return {"content": new_content, "injected": True, "method": "placeholder_match"}

        return {"content": content, "injected": False, "method": None}

    def _append_orphan_captions(
        self,
        content: str,
        orphan_captions: list[tuple[str, str, int | None]],
    ) -> str:
        """Append orphan captions to document end."""
        if not orphan_captions:
            return content
        appendix = "\n\n---\n\n## 📎 추가 자료 설명\n\n"
        for i, (caption, cap_type, page) in enumerate(orphan_captions, 1):
            if cap_type == "table":
                appendix += f"### 표 {i}\n\n{caption}\n\n"
            else:
                page_info = f" (페이지 {page})" if page else ""
                appendix += f"### 이미지 {i}{page_info}\n\n> {caption}\n\n"
        return content + appendix

    async def parse_file(
        self,
        file_path: str,
        output_format: str = "markdown",  # Changed: Markdown 기본값
        caption_images: bool = True,
    ) -> ParsingResult:
        """
        Parse a document from a file path.
        
        Args:
            file_path: Path to the document file
            output_format: Output format
            caption_images: Whether to generate captions
            
        Returns:
            ParsingResult
        """
        path = Path(file_path)
        with open(path, "rb") as f:
            content = f.read()
        
        return await self.parse_document(
            content,
            path.name,
            output_format,
            caption_images=caption_images,
        )
