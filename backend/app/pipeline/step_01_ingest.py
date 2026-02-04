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
        # Use --drive-root-folder-id to access shared folder by ID
        cmd = [
            "rclone",
            "sync",
            "gdrive:",  # Use root, folder specified via --drive-root-folder-id
            dest,
            "--drive-root-folder-id", drive_folder_id,  # Access folder by ID
            "--drive-service-account-file", os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ),
            # Mac/Windows compatibility: normalize Unicode filenames
            "--drive-encoding", "None",
            # Skip Google Drive shortcuts
            "--drive-skip-shortcuts",
            # Progress and logging
            "--progress",
            "--log-level", "INFO",
            "--stats", "1s",
        ]

        # Export Google Workspace files to processable formats
        if export_google_docs:
            cmd.extend(["--drive-export-formats", RCLONE_EXPORT_FORMATS])

        # Add exclude patterns (skip Google Forms etc.)
        for pattern in RCLONE_EXCLUDE_PATTERNS:
            cmd.extend(["--exclude", pattern])

        logger.info("Starting rclone sync", folder_id=drive_folder_id, dest=dest)

        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                timeout=3600,  # 1 hour timeout
            )

            # Decode output with error handling for Korean filenames
            try:
                stdout = result.stdout.decode("utf-8", errors="replace")
                stderr = result.stderr.decode("utf-8", errors="replace")
            except Exception:
                stdout = ""
                stderr = ""

            sync_log = stdout.split("\n") if stdout else []
            errors = stderr.split("\n") if stderr else []

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
        skipped_files: list[str] = []
        skipped_extensions: dict[str, int] = {}

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
                skipped_files.append(relative_path)
                ext_key = extension if extension else "(no extension)"
                skipped_extensions[ext_key] = skipped_extensions.get(ext_key, 0) + 1
                logger.warning(
                    "[SCAN] Skipping unsupported file",
                    path=relative_path,
                    extension=ext_key,
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

        # Log summary of skipped files
        if skipped_files:
            logger.warning(
                "[SCAN] Files skipped due to unsupported extension",
                skipped_count=len(skipped_files),
                skipped_by_extension=skipped_extensions,
                skipped_files=skipped_files,
            )

        logger.info(
            "[SCAN] File scan completed",
            total_files=len(files),
            skipped_files=len(skipped_files),
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

        # Get existing drive_ids from DB (unique constraint is on drive_id)
        existing_result = await db.execute(select(Document.drive_id))
        existing_ids = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]

            # Generate unique drive_id based on path
            drive_id = f"local:{file_path}"

            # Check for duplicates using drive_id (matches DB unique constraint)
            if drive_id in existing_ids:
                skipped_count += 1
                logger.debug(
                    "[REGISTER] Skipping duplicate",
                    drive_id=drive_id,
                )
                continue

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

    async def register_google_forms_to_db(
        self,
        db: AsyncSession,
        forms: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Register Google Forms to the database using their webViewLink.

        Google Forms cannot be downloaded, so we store them as References
        with COMPLETED status immediately.

        Args:
            db: Database session.
            forms: List of Google Form metadata from Google Drive API.
                   Each dict should have: id, name, webViewLink, modifiedTime

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
                logger.debug(
                    "[FORMS] Skipping duplicate form",
                    drive_id=drive_id,
                )
                skipped_count += 1
                continue

            doc = Document(
                drive_id=drive_id,
                drive_name=self.normalize_filename(form_info.get("name", "Untitled Form")),
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

            logger.debug(
                "[FORMS] Added new Google Form",
                drive_id=drive_id,
                name=form_info.get("name"),
            )

        await db.commit()

        logger.info(
            "[FORMS] Google Forms registered to database",
            new=new_count,
            skipped=skipped_count,
            total=len(forms),
        )

        return {"new": new_count, "skipped": skipped_count, "total": len(forms)}

    async def run_step1(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        skip_sync: bool = False,
    ) -> dict[str, Any]:
        """
        Execute full Step 1 pipeline: rclone sync + Forms collection + DB registration.

        This is the main entry point for Step 1 of the RAG pipeline.

        Args:
            db: Database session for registering documents.
            folder_id: Google Drive folder ID to sync.
                       Uses settings.GOOGLE_DRIVE_FOLDER_ID if not provided.
            skip_sync: If True, skip rclone sync (useful for testing or when files
                       are already downloaded).

        Returns:
            Dictionary with complete Step 1 results:
            {
                "folder_id": str,
                "sync": {...},      # rclone sync result
                "forms": {...},     # Google Forms collection result
                "files": {...},     # File registration result
                "success": bool,
            }
        """
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID or ""

        result: dict[str, Any] = {
            "folder_id": folder_id,
            "sync": None,
            "forms": None,
            "files": None,
            "success": False,
        }

        try:
            # Step 1a: Sync files from Google Drive using rclone
            if not skip_sync and folder_id:
                logger.info(
                    "[STEP1] Starting rclone sync",
                    folder_id=folder_id,
                )
                sync_result = await self.sync_from_drive(folder_id)
                result["sync"] = {
                    "files_synced": sync_result.files_synced,
                    "files_failed": sync_result.files_failed,
                    "total_size_bytes": sync_result.total_size_bytes,
                    "errors": sync_result.errors[:5] if sync_result.errors else [],
                }

                if sync_result.files_failed > 0:
                    logger.warning(
                        "[STEP1] Some files failed to sync",
                        failed=sync_result.files_failed,
                        errors=sync_result.errors[:5],
                    )
            else:
                logger.info("[STEP1] Skipping rclone sync")
                result["sync"] = {"skipped": True}

            # Step 1b: Collect Google Forms URLs via Drive API
            if folder_id:
                logger.info(
                    "[STEP1] Collecting Google Forms",
                    folder_id=folder_id,
                )
                try:
                    forms = await self.collect_google_form_links(folder_id)
                    forms_result = await self.register_google_forms_to_db(db, forms)
                    result["forms"] = {
                        "found": len(forms),
                        "new": forms_result["new"],
                        "skipped": forms_result["skipped"],
                    }
                except Exception as e:
                    logger.warning(
                        "[STEP1] Failed to collect Google Forms",
                        error=str(e),
                    )
                    result["forms"] = {"error": str(e)}
            else:
                result["forms"] = {"skipped": True, "reason": "No folder_id provided"}

            # Step 1c: Scan and register local files to DB
            logger.info("[STEP1] Scanning and registering local files")
            files = self.scan_local_files()
            files_result = await self.register_files_to_db(db, files)
            result["files"] = {
                "scanned": len(files),
                "new": files_result["new"],
                "skipped": files_result["skipped"],
            }

            result["success"] = True
            logger.info(
                "[STEP1] Step 1 completed successfully",
                files_synced=result["sync"].get("files_synced", 0) if isinstance(result["sync"], dict) else 0,
                forms_new=result["forms"].get("new", 0) if isinstance(result["forms"], dict) else 0,
                files_new=result["files"]["new"],
            )

        except Exception as e:
            logger.exception("[STEP1] Step 1 failed", error=str(e))
            result["error"] = str(e)
            raise

        return result
