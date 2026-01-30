"""
Ingestion service for syncing and registering documents from Google Drive.

Uses rclone for file synchronization and registers files to the database.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus, DocumentType

logger = structlog.get_logger()

# File extension to DocumentType mapping
# Google Workspace files are exported as: .docx (Docs), .xlsx (Sheets), .pptx (Slides)
EXTENSION_TO_DOCTYPE: dict[str, DocumentType] = {
    # Google Workspace exports
    ".docx": DocumentType.GOOGLE_DOC,
    ".xlsx": DocumentType.GOOGLE_SHEET,
    ".pptx": DocumentType.OTHER,  # Google Slides
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
    ".docx",   # Google Docs export
    ".xlsx",   # Google Sheets export
    ".pptx",   # Google Slides export
    ".pdf",
    ".hwp",
    ".hwpx",
    ".txt",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
}


class IngestionService:
    """Service for managing document ingestion from Google Drive via rclone."""

    def __init__(
        self,
        sync_script_path: str = "/app/scripts/sync_drive.sh",
        data_path: str = "/app/data/raw",
        log_path: str = "/app/logs",
    ) -> None:
        """
        Initialize ingestion service.

        Args:
            sync_script_path: Path to the rclone sync script.
            data_path: Local path where files are synced.
            log_path: Path for log files.
        """
        self.sync_script_path = Path(sync_script_path)
        self.data_path = Path(data_path)
        self.log_path = Path(log_path)

    def run_sync(self, folder_id: str | None = None) -> dict[str, Any]:
        """
        Execute rclone sync script.

        Args:
            folder_id: Google Drive folder ID to sync. Uses env default if not provided.

        Returns:
            Dictionary with sync result information.

        Raises:
            RuntimeError: If sync script fails.
        """
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID
        if not folder_id:
            raise ValueError("folder_id is required")

        # Prepare environment
        env = os.environ.copy()
        env["GOOGLE_DRIVE_FOLDER_ID"] = folder_id
        env["SYNC_LOCAL_PATH"] = str(self.data_path)
        env["SYNC_LOG_FILE"] = str(self.log_path / "sync.log")

        logger.info("Starting rclone sync", folder_id=folder_id, data_path=str(self.data_path))

        try:
            result = subprocess.run(
                [str(self.sync_script_path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if result.returncode != 0:
                logger.error(
                    "Rclone sync failed",
                    returncode=result.returncode,
                    stderr=result.stderr,
                )
                raise RuntimeError(f"Sync failed: {result.stderr}")

            logger.info("Rclone sync completed successfully")
            return {
                "success": True,
                "returncode": result.returncode,
                "stdout": result.stdout,
            }

        except subprocess.TimeoutExpired:
            logger.error("Rclone sync timed out")
            raise RuntimeError("Sync timed out after 1 hour")

        except FileNotFoundError:
            logger.error("Sync script not found", path=str(self.sync_script_path))
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

            # Get file stats
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
        # Get existing file paths to avoid duplicates
        existing_result = await db.execute(select(Document.drive_path))
        existing_paths = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]

            # Skip if already exists
            if file_path in existing_paths:
                skipped_count += 1
                continue

            # Create unique drive_id from path (since we don't have Google Drive ID)
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

        return {
            "new": new_count,
            "skipped": skipped_count,
            "total": len(files),
        }

    @staticmethod
    def _get_mime_type(extension: str) -> str:
        """Get MIME type from file extension."""
        mime_types = {
            # Google Workspace exports
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            # Native documents
            ".pdf": "application/pdf",
            ".hwp": "application/x-hwp",
            ".hwpx": "application/hwp+zip",
            ".txt": "text/plain",
            ".csv": "text/csv",
            # Images
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        return mime_types.get(extension, "application/octet-stream")

    async def full_ingestion(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        skip_sync: bool = False,
    ) -> dict[str, Any]:
        """
        Run full ingestion pipeline: sync + scan + register.

        Args:
            db: Database session.
            folder_id: Google Drive folder ID.
            skip_sync: If True, skip rclone sync and only scan/register.

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
            # Step 1: Sync files from Google Drive
            if not skip_sync:
                sync_result = self.run_sync(folder_id)
                result["sync"] = sync_result

            # Step 2: Scan local files
            files = self.scan_local_files()
            result["scan"] = {"file_count": len(files)}

            # Step 3: Register to database
            register_result = await self.register_files_to_db(db, files)
            result["register"] = register_result

            result["success"] = True
            logger.info("Full ingestion completed", result=result)

        except Exception as e:
            logger.error("Ingestion failed", error=str(e))
            result["error"] = str(e)
            raise

        return result


# Singleton instance
ingestion_service = IngestionService()
