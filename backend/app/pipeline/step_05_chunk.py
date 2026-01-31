"""Step 5: Chunking - Split documents into Parent-Child chunks for RAG.

This module handles document chunking with:
1. Parent chunks: Complete agenda items (## headers)
2. Child chunks: Smaller segments for precise vector search
3. Overlap handling for context preservation
"""

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.core.config import settings

logger = structlog.get_logger()


@dataclass
class ChunkData:
    """Data for a single chunk."""
    
    content: str
    is_parent: bool
    parent_content: str | None  # Full parent content for child chunks
    parent_index: int | None  # Index of parent chunk for linking
    chunk_index: int
    chunk_type: str  # text, table, header
    section_header: str | None
    token_count: int | None = None
    start_char: int | None = None
    end_char: int | None = None
    metadata: dict = field(default_factory=dict)


class ChunkingService:
    """
    Service for splitting documents into Parent-Child chunks.
    
    Strategy:
        1. Split by ## headers → Parent chunks (complete agenda items)
        2. Split parents into smaller children → Child chunks
        3. Store parent_content on children for context retrieval
    
    Search flow:
        1. Query → embed → search child chunks (precision)
        2. Return parent_content of matched children (context)
        3. LLM uses full parent content for answer generation
    """

    def __init__(
        self,
        parent_chunk_size: int = 4000,
        child_chunk_size: int = 500,
        child_chunk_overlap: int = 50,  # ~10% overlap
    ):
        """
        Initialize chunking service.
        
        Args:
            parent_chunk_size: Max size for parent chunks
            child_chunk_size: Target size for child chunks
            child_chunk_overlap: Overlap between child chunks
        """
        self.parent_chunk_size = parent_chunk_size
        self.child_chunk_size = child_chunk_size
        self.child_chunk_overlap = child_chunk_overlap

        # Headers to split on for parent chunks
        self.headers_to_split_on = [
            ("#", "agenda_type"),     # 보고안건, 논의안건
            ("##", "agenda_item"),    # Individual agenda items
        ]

        # Markdown splitter for parent chunks
        self.markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self.headers_to_split_on,
            strip_headers=False,  # Keep headers in content
        )

        # Recursive splitter for child chunks
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_chunk_overlap,
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
            length_function=len,
        )

    def chunk_document(
        self,
        content: str,
        document_metadata: dict | None = None,
    ) -> list[ChunkData]:
        """
        Split a document into Parent-Child chunks.
        
        Args:
            content: Preprocessed document content (Markdown)
            document_metadata: Additional metadata to attach to chunks
            
        Returns:
            List of ChunkData objects (parents and children)
        """
        metadata = document_metadata or {}
        all_chunks: list[ChunkData] = []
        parent_index = 0
        chunk_index = 0

        # Step 1: Split by Markdown headers for parent chunks
        try:
            header_splits = self.markdown_splitter.split_text(content)
        except Exception as e:
            logger.warning("Markdown splitting failed, using fallback", error=str(e))
            # Fallback: treat entire content as one parent
            header_splits = [type('obj', (object,), {
                'page_content': content,
                'metadata': {}
            })()]

        for split in header_splits:
            split_content = split.page_content if hasattr(split, 'page_content') else str(split)
            split_metadata = split.metadata if hasattr(split, 'metadata') else {}
            
            if not split_content.strip():
                continue

            # Extract section header from metadata or content
            section_header = self._extract_section_header(split_content, split_metadata)

            # Create parent chunk
            parent_chunk = ChunkData(
                content=split_content,
                is_parent=True,
                parent_content=None,  # Parents don't have parent_content
                parent_index=None,
                chunk_index=chunk_index,
                chunk_type="text",
                section_header=section_header,
                token_count=self._estimate_tokens(split_content),
                metadata={**metadata, **split_metadata},
            )
            all_chunks.append(parent_chunk)
            current_parent_index = chunk_index
            chunk_index += 1

            # Step 2: Split parent into child chunks
            if len(split_content) > self.child_chunk_size:
                child_splits = self.child_splitter.split_text(split_content)
                
                for i, child_content in enumerate(child_splits):
                    if not child_content.strip():
                        continue
                    
                    child_chunk = ChunkData(
                        content=child_content,
                        is_parent=False,
                        parent_content=split_content,  # Store full parent
                        parent_index=current_parent_index,
                        chunk_index=chunk_index,
                        chunk_type="text",
                        section_header=section_header,
                        token_count=self._estimate_tokens(child_content),
                        metadata={
                            **metadata,
                            **split_metadata,
                            "child_position": i,
                            "total_children": len(child_splits),
                        },
                    )
                    all_chunks.append(child_chunk)
                    chunk_index += 1
            else:
                # Parent is small enough, create single child with same content
                child_chunk = ChunkData(
                    content=split_content,
                    is_parent=False,
                    parent_content=split_content,
                    parent_index=current_parent_index,
                    chunk_index=chunk_index,
                    chunk_type="text",
                    section_header=section_header,
                    token_count=self._estimate_tokens(split_content),
                    metadata={
                        **metadata,
                        **split_metadata,
                        "child_position": 0,
                        "total_children": 1,
                    },
                )
                all_chunks.append(child_chunk)
                chunk_index += 1

            parent_index += 1

        logger.info(
            "Chunking completed",
            total_chunks=len(all_chunks),
            parent_chunks=sum(1 for c in all_chunks if c.is_parent),
            child_chunks=sum(1 for c in all_chunks if not c.is_parent),
        )

        return all_chunks

    def _extract_section_header(
        self,
        content: str,
        metadata: dict,
    ) -> str | None:
        """Extract section header from content or metadata."""
        # Try metadata first
        if metadata.get("agenda_item"):
            return metadata["agenda_item"]
        if metadata.get("agenda_type"):
            return metadata["agenda_type"]

        # Extract from content (first line if it's a header)
        lines = content.strip().split('\n')
        if lines and lines[0].startswith('#'):
            return lines[0].lstrip('#').strip()
        
        return None

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Uses rough approximation: ~4 characters per token for Korean/English mix.
        """
        return len(text) // 4

    def chunk_with_tables(
        self,
        content: str,
        tables: list[dict],
        document_metadata: dict | None = None,
    ) -> list[ChunkData]:
        """
        Chunk document with special handling for tables.
        
        Tables are kept as separate chunks to preserve structure.
        
        Args:
            content: Document content
            tables: List of table data from parsing
            document_metadata: Additional metadata
            
        Returns:
            List of ChunkData including table chunks
        """
        # First, chunk the text content
        text_chunks = self.chunk_document(content, document_metadata)
        
        # Add table chunks
        metadata = document_metadata or {}
        for i, table in enumerate(tables):
            table_content = table.get("content", "")
            if not table_content:
                continue
            
            table_chunk = ChunkData(
                content=table_content,
                is_parent=True,  # Tables are parents
                parent_content=None,
                parent_index=None,
                chunk_index=len(text_chunks) + i,
                chunk_type="table",
                section_header=None,
                token_count=self._estimate_tokens(table_content),
                metadata={
                    **metadata,
                    "table_index": i,
                    "page": table.get("page"),
                },
            )
            text_chunks.append(table_chunk)
        
        return text_chunks

    def get_parent_chunks(self, chunks: list[ChunkData]) -> list[ChunkData]:
        """Filter and return only parent chunks."""
        return [c for c in chunks if c.is_parent]

    def get_child_chunks(self, chunks: list[ChunkData]) -> list[ChunkData]:
        """Filter and return only child chunks."""
        return [c for c in chunks if not c.is_parent]

    def group_by_parent(
        self,
        chunks: list[ChunkData],
    ) -> dict[int, list[ChunkData]]:
        """Group child chunks by their parent index."""
        groups: dict[int, list[ChunkData]] = {}
        for chunk in chunks:
            if chunk.parent_index is not None:
                if chunk.parent_index not in groups:
                    groups[chunk.parent_index] = []
                groups[chunk.parent_index].append(chunk)
        return groups
