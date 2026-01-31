"""Step 1: Ingestion - Collect documents from Google Drive via rclone.

This module handles the initial document collection from Google Drive
to Google Cloud Storage using rclone for efficient batch synchronization.

Note for Mac team member:
    - File encoding issues (NFC/NFD) may occur on macOS
    - Use rclone with --drive-encoding option for compatibility
    - Ensure UTF-8 normalization for Korean filenames

Merged from teammate's ingestion.py:
    - rclone include/exclude patterns
    - EXTENSION_TO_DOCTYPE mapping
    - register_files_to_db() method
"""

import asyncio
import os
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus, DocumentType

logger = structlog.get_logger()

# =============================================================================
# Constants from teammate's ingestion.py
# =============================================================================

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

# rclone configuration (from teammate)
RCLONE_REMOTE_NAME = "gdrive"
RCLONE_EXPORT_FORMATS = "docx,xlsx,pptx,pdf"
RCLONE_INCLUDE_PATTERNS = [
    "*.docx", "*.xlsx", "*.pptx", "*.pdf",
    "*.hwp", "*.hwpx", "*.txt", "*.csv",
    "*.jpg", "*.jpeg", "*.png",
]
RCLONE_EXCLUDE_PATTERNS = ["*.gform"]


def _get_mime_type(extension: str) -> str:
    """Get MIME type from file extension."""
    mime_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".hwp": "application/x-hwp",
        ".hwpx": "application/x-hwpx",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }
    return mime_map.get(extension.lower(), "application/octet-stream")


@dataclass
class IngestionResult:
    """Result of ingestion operation."""

    files_synced: int
    files_failed: int
    total_size_bytes: int
    sync_log: list[str]
    errors: list[str]


class IngestionService:
    """
    Service for ingesting documents from Google Drive.
    
    Uses rclone for efficient batch synchronization to GCS.
    Handles file format conversions as per Step 1 requirements:
        - .docx → can be processed by Upstage
        - .xlsx → can be processed 
        - .pdf, .hwp → downloaded as-is
        - .gform → links only (Reference table)
    
    Environment considerations:
        - Mac users: Enable --drive-encoding for NFC/NFD compatibility
        - Windows/Linux: Standard UTF-8 handling
    """

    def __init__(self, work_dir: str | None = None):
        """
        Initialize ingestion service.
        
        Args:
            work_dir: Working directory for temporary files. 
                     Defaults to settings.DATA_RAW_PATH or /tmp/council-ai/ingestion
        """
        self.work_dir = Path(work_dir or settings.DATA_RAW_PATH or "/tmp/council-ai/ingestion")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.gcs_bucket = settings.GCS_BUCKET_NAME
        self.processed_path = Path(settings.DATA_PROCESSED_PATH or "/app/data/processed")
        self.processed_path.mkdir(parents=True, exist_ok=True)

    def normalize_filename(self, filename: str) -> str:
        """
        Normalize filename to NFC form for cross-platform compatibility.
        
        Mac uses NFD (decomposed), Linux/Windows use NFC (composed).
        This ensures consistent handling regardless of source OS.
        
        Args:
            filename: Original filename
            
        Returns:
            NFC-normalized filename
        """
        return unicodedata.normalize("NFC", filename)

    async def sync_from_drive(
        self,
        drive_folder_id: str,
        destination_path: str | None = None,
        export_google_docs: bool = True,
    ) -> IngestionResult:
        """
        Synchronize files from Google Drive folder to local/GCS.
        
        Uses rclone with Service Account authentication.
        
        Args:
            drive_folder_id: Google Drive folder ID to sync
            destination_path: Local path or GCS path for output
            export_google_docs: If True, export Google Docs/Sheets to Office formats
            
        Returns:
            IngestionResult with sync statistics
        """
        dest = destination_path or str(self.work_dir / drive_folder_id)
        Path(dest).mkdir(parents=True, exist_ok=True)

        # Build rclone command
        # NOTE: Requires rclone configured with 'gdrive' remote using Service Account
        cmd = [
            "rclone",
            "sync",
            f"gdrive:{drive_folder_id}",
            dest,
            "--drive-service-account-file", os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ),
            # Mac/Windows compatibility: normalize Unicode filenames
            "--drive-encoding", "None",
            # Export Google Workspace files to processable formats
            "--drive-export-formats", "docx,xlsx,pptx" if export_google_docs else "",
            # Skip Google Forms (will be handled separately as References)
            "--drive-skip-shortcuts",
            # Progress and logging
            "--progress",
            "--log-level", "INFO",
            "--stats", "1s",
            "-v",
        ]

        # Remove empty arguments
        cmd = [arg for arg in cmd if arg]

        logger.info("Starting rclone sync", folder_id=drive_folder_id, dest=dest)

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            sync_log = result.stdout.split("\n") if result.stdout else []
            errors = result.stderr.split("\n") if result.stderr else []

            # Count synced files
            files_synced = self._count_files(dest)
            total_size = self._get_total_size(dest)

            logger.info(
                "Rclone sync completed",
                files_synced=files_synced,
                total_size=total_size,
                return_code=result.returncode,
            )

            return IngestionResult(
                files_synced=files_synced,
                files_failed=0 if result.returncode == 0 else 1,
                total_size_bytes=total_size,
                sync_log=sync_log,
                errors=[e for e in errors if e.strip()],
            )

        except subprocess.TimeoutExpired:
            logger.error("Rclone sync timeout", folder_id=drive_folder_id)
            return IngestionResult(
                files_synced=0,
                files_failed=1,
                total_size_bytes=0,
                sync_log=[],
                errors=["Sync operation timed out after 1 hour"],
            )

    async def list_synced_files(
        self, 
        directory: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List all files in the synced directory with metadata.
        
        Args:
            directory: Directory to list (defaults to work_dir)
            
        Returns:
            List of file info dictionaries with normalized paths
        """
        target_dir = Path(directory) if directory else self.work_dir
        files = []

        for path in target_dir.rglob("*"):
            if path.is_file():
                # Normalize filename for cross-platform compatibility
                normalized_name = self.normalize_filename(path.name)
                relative_path = self.normalize_filename(str(path.relative_to(target_dir)))
                
                files.append({
                    "path": str(path),
                    "name": normalized_name,
                    "relative_path": relative_path,
                    "size": path.stat().st_size,
                    "extension": path.suffix.lower(),
                    "parent_folder": self.normalize_filename(path.parent.name),
                    "full_folder_path": self.normalize_filename(
                        str(path.parent.relative_to(target_dir))
                    ),
                })

        return files

    async def collect_google_form_links(
        self, 
        drive_folder_id: str,
    ) -> list[dict[str, str]]:
        """
        Collect Google Form links for Reference table (not downloaded).
        
        Google Forms cannot be downloaded/converted, so we only store links.
        
        Args:
            drive_folder_id: Google Drive folder ID
            
        Returns:
            List of form info with links
        """
        from app.services.google.drive import GoogleDriveService
        
        drive_service = GoogleDriveService()
        
        # Search for Google Forms in the folder
        forms = drive_service.search_files(
            folder_id=drive_folder_id,
            mime_type="application/vnd.google-apps.form",
            recursive=True,
        )

        return [
            {
                "id": form["id"],
                "name": self.normalize_filename(form["name"]),
                "link": f"https://docs.google.com/forms/d/{form['id']}/edit",
                "view_link": f"https://docs.google.com/forms/d/{form['id']}/viewform",
            }
            for form in forms
        ]

    def _count_files(self, directory: str) -> int:
        """Count files in directory recursively."""
        return sum(1 for _ in Path(directory).rglob("*") if _.is_file())

    def _get_total_size(self, directory: str) -> int:
        """Get total size of files in directory."""
        return sum(f.stat().st_size for f in Path(directory).rglob("*") if f.is_file())

    async def cleanup(self, directory: str | None = None) -> None:
        """
        Clean up temporary ingestion files.
        
        Args:
            directory: Directory to clean (defaults to work_dir)
        """
        target = Path(directory) if directory else self.work_dir
        if target.exists():
            shutil.rmtree(target)
            logger.info("Cleaned up ingestion directory", path=str(target))

    # =========================================================================
    # Methods merged from teammate's ingestion.py
    # =========================================================================

    def scan_local_files(self) -> list[dict[str, Any]]:
        """
        Scan local data directory for synced files recursively.
        
        Returns:
            List of file metadata dictionaries with doc_type mapping.
        """
        files = []

        logger.info(
            "[SCAN] Starting recursive file scan",
            data_path=str(self.work_dir),
            exists=self.work_dir.exists(),
        )

        if not self.work_dir.exists():
            logger.warning("[SCAN] Data path does not exist", path=str(self.work_dir))
            return files

        for file_path in self.work_dir.rglob("*"):
            if not file_path.is_file():
                continue
                
            extension = file_path.suffix.lower()
            relative_path = str(file_path.relative_to(self.work_dir))

            if extension not in SUPPORTED_EXTENSIONS:
                logger.debug(
                    "[SCAN] Skipping unsupported file",
                    path=relative_path,
                    extension=extension,
                )
                continue

            stat = file_path.stat()
            file_info = {
                "name": self.normalize_filename(file_path.name),
                "path": self.normalize_filename(relative_path),
                "full_path": str(file_path),
                "extension": extension,
                "doc_type": EXTENSION_TO_DOCTYPE.get(extension, DocumentType.OTHER),
                "size": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
            files.append(file_info)

        logger.info(
            "[SCAN] File scan completed",
            total_files=len(files),
        )

        return files

    async def register_files_to_db(
        self,
        db: AsyncSession,
        files: list[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """
        Register scanned files to the database.
        
        Merged from teammate's ingestion.py with async support.
        
        Args:
            db: Database session.
            files: List of file metadata from scan_local_files().
                   If None, will scan automatically.
        
        Returns:
            Dictionary with new, skipped, and total counts.
        """
        if files is None:
            files = self.scan_local_files()
            
        logger.info(
            "[REGISTER] Starting file registration",
            files_to_process=len(files),
        )

        # Get existing paths from DB
        existing_result = await db.execute(select(Document.drive_path))
        existing_paths = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]

            # Check for duplicates
            if file_path in existing_paths:
                skipped_count += 1
                continue

            # Generate unique drive_id based on path
            drive_id = f"local:{file_path}"

            doc = Document(
                drive_id=drive_id,
                drive_name=file_info["name"],
                drive_path=file_path,
                mime_type=_get_mime_type(file_info["extension"]),
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

            logger.debug(
                "[REGISTER] Added new document",
                drive_id=drive_id,
                drive_path=file_path,
            )

        await db.commit()

        logger.info(
            "[REGISTER] Registration completed",
            new=new_count,
            skipped=skipped_count,
            total=len(files),
        )

        return {"new": new_count, "skipped": skipped_count, "total": len(files)}

    async def sync_folder_to_db(
        self,
        db: AsyncSession,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Sync files from data/raw folder to DB.
        
        Merged from teammate's ingestion.py.
        
        Args:
            db: Database session.
            force: If True, scan and register even if DB is not empty.
        
        Returns:
            Dictionary with sync results.
        """
        logger.info("[DB SYNC] Starting folder-to-DB sync")

        # Check if DB has any documents
        doc_count_result = await db.execute(select(Document.id).limit(1))
        db_has_docs = doc_count_result.scalar() is not None

        if db_has_docs and not force:
            logger.info("[DB SYNC] DB already has documents, skipping sync")
            return {
                "synced": False,
                "reason": "DB already has documents",
                "new": 0,
                "skipped": 0,
                "total": 0,
            }

        # Scan and register files
        files = self.scan_local_files()

        if not files:
            logger.warning("[DB SYNC] No files found in data/raw directory")
            return {
                "synced": True,
                "reason": "No files found",
                "new": 0,
                "skipped": 0,
                "total": 0,
            }

        result = await self.register_files_to_db(db, files)

        logger.info(
            "[DB SYNC] Folder-to-DB sync completed",
            new=result["new"],
            skipped=result["skipped"],
            total=result["total"],
        )

        return {
            "synced": True,
            "reason": "Files registered",
            **result,
        }
