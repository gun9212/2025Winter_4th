"""
Ingestion service for hybrid document collection from Google Drive.

Combines:
- rclone for file synchronization (downloadable files)
- Google Drive API for Google Forms (URL only)
- Upstage Parser for document parsing and content extraction
"""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus, DocumentType

logger = structlog.get_logger()

# File extension to DocumentType mapping
EXTENSION_TO_DOCTYPE: dict[str, DocumentType] = {
    # Google Workspace exports
    ".docx": DocumentType.GOOGLE_DOC,
    ".xlsx": DocumentType.GOOGLE_SHEET,
    ".pptx": DocumentType.OTHER,
    # Native document formats
    ".pdf": DocumentType.PDF,
    ".hwp": DocumentType.OTHER,
    ".hwpx": DocumentType.OTHER,
    ".txt": DocumentType.OTHER,
    ".csv": DocumentType.OTHER,
    # Image formats
    ".jpg": DocumentType.OTHER,
    ".jpeg": DocumentType.OTHER,
    ".png": DocumentType.OTHER,
}

# Whitelist: Only these file extensions are allowed for ingestion
SUPPORTED_EXTENSIONS: set[str] = {
    ".docx", ".xlsx", ".pptx", ".pdf",
    ".hwp", ".hwpx", ".txt", ".csv",
    ".jpg", ".jpeg", ".png",
}

# rclone configuration
RCLONE_REMOTE_NAME = "gdrive"
RCLONE_EXPORT_FORMATS = "docx,xlsx,pptx,pdf"
RCLONE_INCLUDE_PATTERNS = [
    "*.docx", "*.xlsx", "*.pptx", "*.pdf",
    "*.hwp", "*.hwpx", "*.txt", "*.csv",
    "*.jpg", "*.jpeg", "*.png",
]
RCLONE_EXCLUDE_PATTERNS = ["*.gform"]


class IngestionError(Exception):
    """Exception raised when ingestion fails."""

    pass


class IngestionService:
    """Service for hybrid document ingestion from Google Drive."""

    def __init__(
        self,
        sync_script_path: str = "/app/scripts/sync_drive.sh",
        data_path: str = "/app/data/raw",
        processed_path: str = "/app/data/processed",
        log_path: str = "/app/logs",
    ) -> None:
        """
        Initialize ingestion service.

        Args:
            sync_script_path: Path to the rclone sync script.
            data_path: Local path where files are synced.
            processed_path: Path for parsed/processed files.
            log_path: Path for log files.
        """
        self.sync_script_path = Path(sync_script_path)
        self.data_path = Path(data_path)
        self.processed_path = Path(processed_path)
        self.log_path = Path(log_path)

        # Ensure directories exist
        self.data_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)
        self.log_path.mkdir(parents=True, exist_ok=True)

    def run_rclone_command(
        self,
        folder_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Execute rclone copy command directly with dynamic folder ID.

        Args:
            folder_id: Google Drive folder ID. Uses env default if not provided.
            dry_run: If True, only simulate the sync without downloading.

        Returns:
            Dictionary with sync result information.

        Raises:
            IngestionError: If rclone command fails.
        """
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
        if not folder_id:
            raise IngestionError("GOOGLE_DRIVE_FOLDER_ID is required")

        # Check if rclone is installed
        if not shutil.which("rclone"):
            raise IngestionError("rclone is not installed")

        # Build rclone command
        cmd = [
            "rclone", "copy",
            f"{RCLONE_REMOTE_NAME}:/",
            str(self.data_path),
            f"--drive-root-folder-id={folder_id}",
            f"--drive-export-formats={RCLONE_EXPORT_FORMATS}",
            "--transfers=10",
            "--checkers=8",
            "--contimeout=60s",
            "--timeout=300s",
            "--retries=3",
            "--low-level-retries=10",
            "--stats=30s",
            "-v",
        ]

        # Add include patterns
        for pattern in RCLONE_INCLUDE_PATTERNS:
            cmd.extend(["--include", pattern])

        # Add exclude patterns
        for pattern in RCLONE_EXCLUDE_PATTERNS:
            cmd.extend(["--exclude", pattern])

        # Exclude everything else not in include list
        cmd.extend(["--exclude", "*"])

        # Add dry-run if requested
        if dry_run:
            cmd.append("--dry-run")

        logger.info(
            "Executing rclone command",
            folder_id=folder_id,
            data_path=str(self.data_path),
            dry_run=dry_run,
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if result.returncode != 0:
                logger.error(
                    "rclone command failed",
                    returncode=result.returncode,
                    stderr=result.stderr,
                )
                raise IngestionError(f"rclone failed: {result.stderr}")

            logger.info("rclone sync completed successfully")
            return {
                "success": True,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "dry_run": dry_run,
            }

        except subprocess.TimeoutExpired:
            raise IngestionError("rclone sync timed out after 1 hour")
        except FileNotFoundError:
            raise IngestionError("rclone command not found")

    def run_sync(self, folder_id: str | None = None) -> dict[str, Any]:
        """
        Execute rclone sync script (legacy method).

        Args:
            folder_id: Google Drive folder ID to sync.

        Returns:
            Dictionary with sync result information.
        """
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
        if not folder_id:
            raise ValueError("folder_id is required")

        env = os.environ.copy()
        env["GOOGLE_DRIVE_FOLDER_ID"] = folder_id
        env["SYNC_LOCAL_PATH"] = str(self.data_path)
        env["SYNC_LOG_FILE"] = str(self.log_path / "sync.log")

        logger.info("Starting rclone sync", folder_id=folder_id)

        try:
            result = subprocess.run(
                [str(self.sync_script_path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Sync failed: {result.stderr}")

            return {
                "success": True,
                "returncode": result.returncode,
                "stdout": result.stdout,
            }

        except subprocess.TimeoutExpired:
            raise RuntimeError("Sync timed out after 1 hour")
        except FileNotFoundError:
            raise RuntimeError(f"Sync script not found: {self.sync_script_path}")

    def scan_local_files(self) -> list[dict[str, Any]]:
        """
        Scan local data directory for synced files.

        Returns:
            List of file metadata dictionaries.
        """
        files = []

        if not self.data_path.exists():
            logger.warning("Data path does not exist", path=str(self.data_path))
            return files

        for file_path in self.data_path.rglob("*"):
            if not file_path.is_file():
                continue

            extension = file_path.suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                continue

            stat = file_path.stat()

            files.append({
                "name": file_path.name,
                "path": str(file_path.relative_to(self.data_path)),
                "full_path": str(file_path),
                "extension": extension,
                "doc_type": EXTENSION_TO_DOCTYPE.get(extension, DocumentType.OTHER),
                "size": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        logger.info("Scanned local files", count=len(files))
        return files

    async def register_files_to_db(
        self,
        db: AsyncSession,
        files: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Register scanned files to the database.

        Args:
            db: Database session.
            files: List of file metadata from scan_local_files().

        Returns:
            Dictionary with counts of new and skipped files.
        """
        existing_result = await db.execute(select(Document.drive_path))
        existing_paths = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]

            if file_path in existing_paths:
                skipped_count += 1
                continue

            drive_id = f"local:{file_path}"

            doc = Document(
                drive_id=drive_id,
                drive_name=file_info["name"],
                drive_path=file_path,
                mime_type=self._get_mime_type(file_info["extension"]),
                doc_type=file_info["doc_type"],
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "full_path": file_info["full_path"],
                    "size": file_info["size"],
                    "modified_time": file_info["modified_time"],
                    "source": "rclone_sync",
                },
            )
            db.add(doc)
            new_count += 1

        await db.commit()

        logger.info(
            "Files registered to database",
            new_count=new_count,
            skipped_count=skipped_count,
        )

        return {"new": new_count, "skipped": skipped_count, "total": len(files)}

    async def register_google_forms_to_db(
        self,
        db: AsyncSession,
        forms: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Register Google Forms to the database using their webViewLink.

        Args:
            db: Database session.
            forms: List of Google Form metadata from Google Drive API.

        Returns:
            Dictionary with counts of new and skipped forms.
        """
        existing_result = await db.execute(select(Document.drive_id))
        existing_ids = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for form_info in forms:
            drive_id = form_info.get("id")

            if drive_id in existing_ids:
                skipped_count += 1
                continue

            doc = Document(
                drive_id=drive_id,
                drive_name=form_info.get("name", "Untitled Form"),
                drive_path=None,
                mime_type="application/vnd.google-apps.form",
                doc_type=DocumentType.GOOGLE_FORM,
                status=DocumentStatus.COMPLETED,
                doc_metadata={
                    "url": form_info.get("webViewLink"),
                    "is_external": True,
                    "modified_time": form_info.get("modifiedTime"),
                    "source": "google_drive_api",
                },
            )
            db.add(doc)
            new_count += 1

        await db.commit()

        logger.info(
            "Google Forms registered to database",
            new_count=new_count,
            skipped_count=skipped_count,
        )

        return {"new": new_count, "skipped": skipped_count, "total": len(forms)}

    async def parse_pending_documents(
        self,
        db: AsyncSession,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Parse pending documents using Upstage Parser and update DB.

        Args:
            db: Database session.
            limit: Maximum number of documents to parse.

        Returns:
            Dictionary with parsing results.
        """
        from app.services.parser.upstage import UpstageDocParser, UpstageParserError

        parser = UpstageDocParser(
            raw_data_path=str(self.data_path),
            processed_data_path=str(self.processed_path),
        )

        # Get pending documents
        result = await db.execute(
            select(Document)
            .where(Document.status == DocumentStatus.PENDING)
            .where(Document.doc_type != DocumentType.GOOGLE_FORM)
            .limit(limit)
        )
        pending_docs = result.scalars().all()

        results = {
            "success": [],
            "failed": [],
            "total": len(pending_docs),
        }

        for doc in pending_docs:
            file_path = doc.doc_metadata.get("full_path") if doc.doc_metadata else None

            if not file_path:
                results["failed"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "error": "No file path in metadata",
                })
                continue

            try:
                # Update status to PROCESSING
                doc.status = DocumentStatus.PROCESSING
                await db.commit()

                # Parse document
                parse_result = await parser.parse_and_save(file_path)

                # Update document with parsed content
                doc.parsed_content = parse_result["content"]
                doc.status = DocumentStatus.COMPLETED
                doc.processed_at = datetime.utcnow()

                # Update metadata with processing info
                if doc.doc_metadata:
                    doc.doc_metadata["processed_path"] = parse_result["output_path"]
                    doc.doc_metadata["content_length"] = parse_result["content_length"]
                    doc.doc_metadata["image_count"] = len(parse_result["images"])

                await db.commit()

                results["success"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "content_length": parse_result["content_length"],
                })

                logger.info(
                    "Document parsed successfully",
                    doc_id=doc.id,
                    name=doc.drive_name,
                )

            except UpstageParserError as e:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                await db.commit()

                results["failed"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "error": str(e),
                })

                logger.error(
                    "Document parsing failed",
                    doc_id=doc.id,
                    name=doc.drive_name,
                    error=str(e),
                )

            except Exception as e:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                await db.commit()

                results["failed"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "error": str(e),
                })

        logger.info(
            "Document parsing batch completed",
            success_count=len(results["success"]),
            failed_count=len(results["failed"]),
        )

        return results

    async def hybrid_ingestion(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        skip_sync: bool = False,
        parse_documents: bool = True,
        parse_limit: int = 50,
    ) -> dict[str, Any]:
        """
        Run full hybrid ingestion pipeline.

        1. rclone sync for downloadable files
        2. Google Drive API for Google Forms URLs
        3. Scan and register files to DB
        4. Parse documents with Upstage

        Args:
            db: Database session.
            folder_id: Google Drive folder ID.
            skip_sync: Skip rclone sync step.
            parse_documents: Whether to parse documents after registration.
            parse_limit: Maximum documents to parse.

        Returns:
            Dictionary with complete ingestion results.
        """
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID

        result = {
            "folder_id": folder_id,
            "sync": None,
            "forms": None,
            "files": None,
            "parsing": None,
            "success": False,
        }

        try:
            # Step 1: Sync files from Google Drive using rclone
            if not skip_sync:
                logger.info("Step 1: Starting rclone sync...")
                sync_result = self.run_rclone_command(folder_id)
                result["sync"] = {
                    "success": sync_result["success"],
                    "message": "rclone sync completed",
                }

            # Step 2: Collect Google Forms URLs via API
            logger.info("Step 2: Collecting Google Forms URLs...")
            try:
                from app.services.google.drive import GoogleDriveService

                drive_service = GoogleDriveService()
                forms = drive_service.list_google_forms(folder_id, recursive=True)
                forms_result = await self.register_google_forms_to_db(db, forms)
                result["forms"] = {
                    "found": len(forms),
                    "new": forms_result["new"],
                    "skipped": forms_result["skipped"],
                }
            except Exception as e:
                logger.warning("Failed to collect Google Forms", error=str(e))
                result["forms"] = {"error": str(e)}

            # Step 3: Scan and register local files
            logger.info("Step 3: Scanning and registering local files...")
            files = self.scan_local_files()
            files_result = await self.register_files_to_db(db, files)
            result["files"] = {
                "scanned": len(files),
                "new": files_result["new"],
                "skipped": files_result["skipped"],
            }

            # Step 4: Parse documents with Upstage
            if parse_documents:
                logger.info("Step 4: Parsing documents with Upstage...")
                try:
                    parse_result = await self.parse_pending_documents(db, parse_limit)
                    result["parsing"] = {
                        "total": parse_result["total"],
                        "success": len(parse_result["success"]),
                        "failed": len(parse_result["failed"]),
                    }
                except Exception as e:
                    logger.error("Document parsing failed", error=str(e))
                    result["parsing"] = {"error": str(e)}

            result["success"] = True
            logger.info("Hybrid ingestion completed", result=result)

        except Exception as e:
            logger.error("Hybrid ingestion failed", error=str(e))
            result["error"] = str(e)
            raise

        return result

    async def full_ingestion(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        skip_sync: bool = False,
    ) -> dict[str, Any]:
        """
        Run full ingestion pipeline (legacy method).

        Args:
            db: Database session.
            folder_id: Google Drive folder ID.
            skip_sync: If True, skip rclone sync.

        Returns:
            Dictionary with ingestion results.
        """
        result = {
            "sync": None,
            "scan": None,
            "register": None,
            "success": False,
        }

        try:
            if not skip_sync:
                sync_result = self.run_sync(folder_id)
                result["sync"] = sync_result

            files = self.scan_local_files()
            result["scan"] = {"file_count": len(files)}

            register_result = await self.register_files_to_db(db, files)
            result["register"] = register_result

            result["success"] = True
            logger.info("Full ingestion completed", result=result)

        except Exception as e:
            logger.error("Ingestion failed", error=str(e))
            result["error"] = str(e)
            raise

        return result

    @staticmethod
    def _get_mime_type(extension: str) -> str:
        """Get MIME type from file extension."""
        mime_types = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pdf": "application/pdf",
            ".hwp": "application/x-hwp",
            ".hwpx": "application/hwp+zip",
            ".txt": "text/plain",
            ".csv": "text/csv",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        return mime_types.get(extension, "application/octet-stream")


# Singleton instance
ingestion_service = IngestionService()
