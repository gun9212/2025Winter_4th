"""Text chunking service for document processing."""

from dataclasses import dataclass
from typing import Any

from langchain.text_splitter import RecursiveCharacterTextSplitter


@dataclass
class TextChunk:
    """Represents a chunk of text with metadata."""

    content: str
    index: int
    chunk_type: str  # "text", "table", "image_caption"
    metadata: dict[str, Any]
    token_count: int


class TextChunker:
    """Service for splitting text into semantic chunks."""

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: list[str] | None = None,
    ) -> None:
        """
        Initialize text chunker.

        Args:
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Number of overlapping characters.
            separators: Custom separators for splitting.
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.separators,
            length_function=len,
        )

    def chunk_text(
        self,
        text: str,
        chunk_type: str = "text",
        base_metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """
        Split text into chunks.

        Args:
            text: Text to split.
            chunk_type: Type of content.
            base_metadata: Metadata to attach to all chunks.

        Returns:
            List of TextChunk objects.
        """
        if not text or not text.strip():
            return []

        # Use LangChain splitter
        splits = self._splitter.split_text(text)

        chunks = []
        for i, split in enumerate(splits):
            metadata = base_metadata.copy() if base_metadata else {}
            metadata["char_start"] = text.find(split)
            metadata["char_end"] = metadata["char_start"] + len(split)

            chunk = TextChunk(
                content=split,
                index=i,
                chunk_type=chunk_type,
                metadata=metadata,
                token_count=self._estimate_tokens(split),
            )
            chunks.append(chunk)

        return chunks

    def chunk_html(
        self,
        html: str,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """
        Extract and chunk text from HTML content.

        Args:
            html: HTML content.
            base_metadata: Metadata to attach.

        Returns:
            List of TextChunk objects.
        """
        from html.parser import HTMLParser
        import re

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text_parts = []
                self.in_table = False

            def handle_starttag(self, tag, attrs):
                if tag == "table":
                    self.in_table = True
                elif tag in ["br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6"]:
                    self.text_parts.append("\n")

            def handle_endtag(self, tag):
                if tag == "table":
                    self.in_table = False
                elif tag in ["p", "div"]:
                    self.text_parts.append("\n")

            def handle_data(self, data):
                if data.strip():
                    self.text_parts.append(data)

        extractor = TextExtractor()
        extractor.feed(html)
        text = "".join(extractor.text_parts)

        # Clean up whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" +", " ", text)

        return self.chunk_text(text, base_metadata=base_metadata)

    def chunk_table(
        self,
        table_content: str,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """
        Process table content as a single chunk.

        Args:
            table_content: Table content (markdown or text).
            base_metadata: Metadata to attach.

        Returns:
            List with single TextChunk.
        """
        # Tables are kept as single chunks to preserve structure
        metadata = base_metadata.copy() if base_metadata else {}

        return [
            TextChunk(
                content=table_content,
                index=0,
                chunk_type="table",
                metadata=metadata,
                token_count=self._estimate_tokens(table_content),
            )
        ]

    def chunk_image_caption(
        self,
        caption: str,
        image_id: str,
        base_metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """
        Create chunk for image caption.

        Args:
            caption: Image caption/description.
            image_id: Original image identifier.
            base_metadata: Metadata to attach.

        Returns:
            List with single TextChunk.
        """
        metadata = base_metadata.copy() if base_metadata else {}
        metadata["image_id"] = image_id

        return [
            TextChunk(
                content=f"[이미지 설명: {caption}]",
                index=0,
                chunk_type="image_caption",
                metadata=metadata,
                token_count=self._estimate_tokens(caption),
            )
        ]

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        Estimate token count for text.

        Uses a simple heuristic (Korean: ~1.5 chars/token, English: ~4 chars/token).

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        # Count Korean characters
        korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7af")
        other_chars = len(text) - korean_chars

        # Rough estimate
        korean_tokens = korean_chars / 1.5
        other_tokens = other_chars / 4

        return int(korean_tokens + other_tokens)
