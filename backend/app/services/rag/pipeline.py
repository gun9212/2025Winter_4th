"""RAG pipeline for end-to-end document processing and querying."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus, DocumentType
from app.models.embedding import DocumentChunk
from app.services.ai.embeddings import EmbeddingService
from app.services.ai.gemini import GeminiService
from app.services.google.drive import GoogleDriveService
from app.services.google.storage import GoogleStorageService
from app.services.parser.upstage import UpstageDocParser
from app.services.rag.chunker import TextChunker
from app.services.rag.retriever import VectorRetriever


# Partner info for business logic
PARTNER_KEYWORDS = ["간식", "회식", "음식", "식사", "커피", "음료"]
PARTNER_INFO = {
    "snacks": {
        "name": "학생회 제휴 간식 업체",
        "discount": "10%",
        "contact": "example@partner.com",
    },
    "dining": {
        "name": "학생회 제휴 식당",
        "discount": "15%",
        "contact": "dining@partner.com",
    },
}


class RAGPipeline:
    """End-to-end RAG pipeline for document ingestion and querying."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.drive_service = GoogleDriveService()
        self.storage_service = GoogleStorageService()
        self.parser = UpstageDocParser()
        self.chunker = TextChunker()
        self.embedding_service = EmbeddingService()
        self.gemini_service = GeminiService()
        self.retriever = VectorRetriever(db)

    async def ingest_folder(
        self,
        folder_id: str,
        recursive: bool = True,
    ) -> list[int]:
        """
        Ingest all documents from a Google Drive folder.

        Args:
            folder_id: Google Drive folder ID.
            recursive: Whether to process subfolders.

        Returns:
            List of created document IDs.
        """
        # List files
        if recursive:
            files = self.drive_service.list_files_recursive(folder_id)
        else:
            files = self.drive_service.list_files(folder_id)

        document_ids = []

        for file in files:
            doc_id = await self.ingest_document(
                drive_id=file["id"],
                drive_name=file["name"],
                mime_type=file.get("mimeType"),
            )
            if doc_id:
                document_ids.append(doc_id)

        return document_ids

    async def ingest_document(
        self,
        drive_id: str,
        drive_name: str,
        mime_type: str | None = None,
    ) -> int | None:
        """
        Ingest a single document.

        Args:
            drive_id: Google Drive file ID.
            drive_name: File name.
            mime_type: File MIME type.

        Returns:
            Created document ID or None if skipped.
        """
        # Determine document type
        doc_type = self._get_document_type(mime_type)
        if doc_type == DocumentType.OTHER:
            return None  # Skip unsupported types

        # Create document record
        document = Document(
            drive_id=drive_id,
            drive_name=drive_name,
            mime_type=mime_type,
            doc_type=doc_type,
            status=DocumentStatus.PROCESSING,
        )
        self.db.add(document)
        await self.db.flush()

        try:
            # Download and convert file
            file_content = await self._download_file(drive_id, mime_type)

            # Parse document
            parse_result = await self.parser.parse_document(
                file_content,
                drive_name,
                output_format="html",
            )

            # Extract and process images
            images = self.parser.extract_images(parse_result)
            image_captions = await self._process_images(images, document.id)

            # Get text content
            text_content = self.parser.get_text_content(parse_result)
            document.parsed_content = text_content

            # Chunk text
            chunks = self.chunker.chunk_html(
                text_content,
                base_metadata={"document_id": document.id},
            )

            # Add image caption chunks
            chunks.extend(image_captions)

            # Generate embeddings and store chunks
            for chunk in chunks:
                embedding = self.embedding_service.embed_text(chunk.content)

                db_chunk = DocumentChunk(
                    document_id=document.id,
                    chunk_index=chunk.index,
                    chunk_type=chunk.chunk_type,
                    content=chunk.content,
                    embedding=embedding,
                    metadata=chunk.metadata,
                    token_count=chunk.token_count,
                )
                self.db.add(db_chunk)

            document.status = DocumentStatus.COMPLETED
            await self.db.commit()

            return document.id

        except Exception as e:
            document.status = DocumentStatus.FAILED
            document.error_message = str(e)
            await self.db.commit()
            raise

    async def search(
        self,
        query: str,
        top_k: int = 5,
        generate_answer: bool = True,
    ) -> dict[str, Any]:
        """
        Search documents and optionally generate an answer.

        Args:
            query: Search query.
            top_k: Number of results.
            generate_answer: Whether to generate LLM answer.

        Returns:
            Search results with optional answer.
        """
        # Check for partner keywords
        partner_info = self._check_partner_keywords(query)

        # Vector search
        results = await self.retriever.search(query, top_k=top_k)

        response = {
            "query": query,
            "results": results,
            "sources": self._extract_sources(results),
            "partner_info": partner_info,
        }

        if generate_answer and results:
            context = [r["content"] for r in results]
            answer = self.gemini_service.generate_answer(
                query, context, partner_info
            )
            response["answer"] = answer

        return response

    async def _download_file(
        self,
        drive_id: str,
        mime_type: str | None,
    ) -> bytes:
        """Download and convert file from Drive."""
        # Google Workspace files need export
        if mime_type and "google-apps" in mime_type:
            if "document" in mime_type:
                return self.drive_service.export_file(
                    drive_id,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            elif "spreadsheet" in mime_type:
                return self.drive_service.export_file(
                    drive_id,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        return self.drive_service.download_file(drive_id)

    async def _process_images(
        self,
        images: list[dict[str, Any]],
        document_id: int,
    ) -> list:
        """Process images: upload to GCS and generate captions."""
        import base64

        caption_chunks = []

        for img in images:
            if not img.get("base64"):
                continue

            # Decode and upload to GCS
            image_bytes = base64.b64decode(img["base64"])
            gcs_path = f"images/doc_{document_id}/{img['id']}.jpg"
            self.storage_service.upload_file(
                image_bytes, gcs_path, content_type="image/jpeg"
            )

            # Generate caption
            caption = self.gemini_service.caption_image(image_bytes)

            # Create caption chunk
            chunks = self.chunker.chunk_image_caption(
                caption,
                img["id"],
                base_metadata={"document_id": document_id, "gcs_path": gcs_path},
            )
            caption_chunks.extend(chunks)

        return caption_chunks

    def _get_document_type(self, mime_type: str | None) -> DocumentType:
        """Map MIME type to DocumentType."""
        if not mime_type:
            return DocumentType.OTHER

        mapping = {
            "application/vnd.google-apps.document": DocumentType.GOOGLE_DOC,
            "application/vnd.google-apps.spreadsheet": DocumentType.GOOGLE_SHEET,
            "application/pdf": DocumentType.PDF,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.DOCX,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentType.XLSX,
        }

        return mapping.get(mime_type, DocumentType.OTHER)

    def _check_partner_keywords(self, query: str) -> dict | None:
        """Check if query contains partner-related keywords."""
        query_lower = query.lower()

        for keyword in PARTNER_KEYWORDS:
            if keyword in query_lower:
                if keyword in ["간식", "커피", "음료"]:
                    return PARTNER_INFO["snacks"]
                else:
                    return PARTNER_INFO["dining"]

        return None

    def _extract_sources(self, results: list[dict[str, Any]]) -> list[dict]:
        """Extract unique source documents from results."""
        seen = set()
        sources = []

        for r in results:
            doc_id = r["document_id"]
            if doc_id not in seen:
                seen.add(doc_id)
                sources.append(
                    {
                        "document_id": doc_id,
                        "document_name": r["document_name"],
                        "drive_id": r["drive_id"],
                        "url": f"https://drive.google.com/file/d/{r['drive_id']}/view",
                    }
                )

        return sources
