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
    # Google native formats (when not exported to Office format)
    ".gdoc": DocumentType.GOOGLE_DOC,
    ".gsheet": DocumentType.GOOGLE_SHEET,
    ".gslides": DocumentType.OTHER,
    "": DocumentType.GOOGLE_DOC,  # Extensionless files treated as Google Docs
}

# Whitelist: Only these file extensions are allowed for ingestion
# Added ".gdoc", ".gsheet" for Google Docs native format (when not exported)
# Added "" for extensionless files (Google Docs sometimes download without extension)
SUPPORTED_EXTENSIONS: set[str] = {
    ".docx", ".xlsx", ".pptx", ".pdf",
    ".hwp", ".hwpx", ".txt", ".csv",
    ".jpg", ".jpeg", ".png",
    ".gdoc", ".gsheet", ".gslides",  # Google native formats
    "",  # Allow extensionless files (will be treated as Google Docs)
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

    async def _fetch_drive_metadata(self, drive_folder_id: str) -> dict[str, dict[str, str]]:
        """
        Fetch metadata (IDs and Names) for all files in the Drive folder using rclone lsjson.
        
        Returns:
            Dictionary mapping relative path to {"id": drive_id, "name": drive_name}.
            Example: {"Folder/File.pdf": {"id": "1A2B3...", "name": "File.pdf"}}
        """
        logger.info("[METADATA] Fetching Drive IDs via rclone lsjson", folder_id=drive_folder_id)
        
        cmd = [
            "rclone",
            "lsjson",
            "gdrive:",
            "--drive-root-folder-id", drive_folder_id,
            "--recursive",
            "--files-only",
            "--no-mimetype",
            "--no-modtime",
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            # Important: Match sync settings
            "--drive-skip-shortcuts", 
        ]
        
        # Include export extensions if needed, but lsjson on drive usually returns original files
        # We need to match what sync does. Sync exports docs to docx.
        # But lsjson will list the *source* files (gdoc).
        # We need a strategy to map source gdoc ID to downloaded docx.
        # The Drive ID of the exported file IS the Drive ID of the source file.
        # So {"Path/To/Doc.docx": "ID_OF_GDOC"} is what we want.
        # rclone lsjson returns "Name" as the name in Drive.
        
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                check=True,
            )
            import json
            items = json.loads(result.stdout)
            
            drive_map: dict[str, dict[str, str]] = {}
            for item in items:
                # rclone lsjson returns path relative to the root folder
                path = item["Path"]
                drive_id = item["ID"]
                name = item["Name"]
                
                # Normalize path for matching
                norm_path = self.normalize_filename(path)
                
                # Handle Google Workspace export mapping
                # If sync exports gdoc -> docx, we need to map the .docx path to this ID
                ext = os.path.splitext(name)[1].lower()
                
                # Map authentic ID and Name to the normalized path
                # This fixes the "Untitled" bug by preserving original Drive file name
                drive_map[norm_path] = {"id": drive_id, "name": name}
                
                # Special handling for exported files:
                # If we have "Doc.gdoc", we anticipate "Doc.docx" locally
                if ext == ".gdoc":
                    docx_path = norm_path.replace(".gdoc", ".docx")
                    docx_name = name.replace(".gdoc", ".docx")
                    drive_map[docx_path] = {"id": drive_id, "name": docx_name}
                elif ext == ".gsheet":
                    xlsx_path = norm_path.replace(".gsheet", ".xlsx")
                    xlsx_name = name.replace(".gsheet", ".xlsx")
                    drive_map[xlsx_path] = {"id": drive_id, "name": xlsx_name}
                elif ext == ".gslides":
                    pptx_path = norm_path.replace(".gslides", ".pptx")
                    pptx_name = name.replace(".gslides", ".pptx")
                    drive_map[pptx_path] = {"id": drive_id, "name": pptx_name}
                    
            logger.info("[METADATA] Fetched metadata for files", count=len(drive_map))
            return drive_map
            
        except Exception as e:
            logger.error("[METADATA] Failed to fetch Drive metadata", error=str(e))
            return {}

    async def register_files_to_db(
        self,
        db: AsyncSession,
        files: list[dict[str, Any]] | None = None,
        drive_id_map: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """
        Register scanned files to the database.
        
        Args:
            db: Database session.
            files: List of file metadata from scan_local_files().
            drive_id_map: Dictionary mapping relative paths to Google Drive IDs.
        
        Returns:
            Dictionary with new, skipped, and total counts.
        """
        if files is None:
            files = self.scan_local_files()
            
        logger.info(
            "[REGISTER] Starting file registration",
            files_to_process=len(files),
            has_id_map=bool(drive_id_map),
        )

        # Get existing drive_ids from DB
        existing_result = await db.execute(select(Document.drive_id))
        existing_ids = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"] # This is relative path
            
            # Determine Drive ID and Name
            # 1. Try to find in the map (Real Google Drive metadata)
            # 2. Fallback to local path (Legacy/Offline support)
            drive_meta = drive_id_map.get(file_path) if drive_id_map else None
            
            if drive_meta and isinstance(drive_meta, dict):
                # New format: {"id": "...", "name": "..."}
                drive_id = drive_meta.get("id", f"local:{file_path}")
                # Use Drive API name instead of local filename (fixes Untitled bug)
                file_name = drive_meta.get("name") or file_info.get("name", "Untitled")
            elif drive_meta and isinstance(drive_meta, str):
                # Legacy format: direct ID string (backward compatibility)
                drive_id = drive_meta
                file_name = file_info.get("name", "Untitled")
            else:
                # Fallback: still use local path but warn
                drive_id = f"local:{file_path}"
                file_name = file_info.get("name", "Untitled")
                if drive_id_map: # Only warn if we expected to find it
                    logger.warning("[REGISTER] ID not found in map, using local", path=file_path)

            # Check for duplicates
            if drive_id in existing_ids:
                skipped_count += 1
                logger.debug("[REGISTER] Skipping duplicate", drive_id=drive_id)
                continue

            doc = Document(
                drive_id=drive_id,
                drive_name=file_name,  # Use Drive API name (not local filename)
                drive_path=file_info["path"], # Consistently store relative path here
                mime_type=_get_mime_type(file_info["extension"]),
                doc_type=file_info["doc_type"],
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "full_path": file_info["full_path"],
                    "size": file_info["size"],
                    "modified_time": file_info["modified_time"],
                    "source": "rclone_sync",
                    "original_path": file_info["path"], # Keep track of path even if ID is opaque
                },
            )
            db.add(doc)
            existing_ids.add(drive_id) # Add to set to prevent dups within same batch
            new_count += 1
            
            logger.debug(
                "[REGISTER] Added new document",
                drive_id=drive_id,
                name=file_name
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
        """
        logger.info("[DB SYNC] Starting folder-to-DB sync")

        doc_count_result = await db.execute(select(Document.id).limit(1))
        db_has_docs = doc_count_result.scalar() is not None

        if db_has_docs and not force:
            logger.info("[DB SYNC] DB already has documents, skipping sync")
            return {"synced": False, "reason": "DB already has documents"}

        files = self.scan_local_files()
        if not files:
            logger.warning("[DB SYNC] No files found")
            return {"synced": True, "reason": "No files found", "new": 0}

        # Try to fetch metadata if we have a folder ID in settings
        drive_map = {}
        if settings.GOOGLE_DRIVE_FOLDER_ID:
            drive_map = await self._fetch_drive_metadata(settings.GOOGLE_DRIVE_FOLDER_ID)

        result = await self.register_files_to_db(db, files, drive_id_map=drive_map)

        logger.info(
            "[DB SYNC] Folder-to-DB sync completed",
            new=result["new"],
            skipped=result["skipped"],
        )

        return {"synced": True, "reason": "Files registered", **result}

    # ... (register_google_forms_to_db remains unchanged) ...

# =========================================================================
    # MISSING METHODS RESTORED
    # =========================================================================

    async def sync_from_drive(self, folder_id: str) -> IngestionResult:
        """
        Sync files from Google Drive to local storage using rclone.
        """
        logger.info("[SYNC] Starting rclone sync", folder_id=folder_id)
        
        # Determine source
        source = f"{RCLONE_REMOTE_NAME}:{folder_id}"
        dest = str(self.work_dir)
        
        # Build command
        cmd = [
            "rclone", "sync", source, dest,
            "--drive-export-formats", RCLONE_EXPORT_FORMATS,
            "--drive-root-folder-id", folder_id,
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            "--create-empty-src-dirs=false",
            "--drive-skip-shortcuts",
            "-v",
        ]
        
        # Add includes
        for pattern in RCLONE_INCLUDE_PATTERNS:
            cmd.extend(["--include", pattern])
            
        # Add excludes
        for pattern in RCLONE_EXCLUDE_PATTERNS:
            cmd.extend(["--exclude", pattern])

        try:
            # Run rclone (blocking call in thread)
            process = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Simple parsing of logs would go here, simplified for restoration
            return IngestionResult(
                files_synced=0, # Placeholder
                files_failed=0,
                total_size_bytes=0,
                sync_log=[process.stderr],
                errors=[]
            )
            
        except subprocess.CalledProcessError as e:
            logger.error("[SYNC] Rclone failed", error=e.stderr)
            return IngestionResult(
                files_synced=0,
                files_failed=1,
                total_size_bytes=0,
                sync_log=[],
                errors=[e.stderr]
            )

    def scan_local_files(self) -> list[dict[str, Any]]:
        """
        Scan local directory for supported files.
        """
        files = []
        for root, _, filenames in os.walk(self.work_dir):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                
                # Treat empty extension as .gdoc (Google Doc)
                if ext == "":
                    ext = ".gdoc"

                full_path = Path(root) / filename
                rel_path = str(full_path.relative_to(self.work_dir))
                
                files.append({
                    "path": rel_path,
                    "full_path": str(full_path),
                    "name": filename,
                    "extension": ext,
                    "size": full_path.stat().st_size,
                    "modified_time": datetime.fromtimestamp(full_path.stat().st_mtime),isoformat(),
                    "doc_type": EXTENSION_TO_DOCTYPE.get(ext, DocumentType.OTHER),
                })
        return files

    async def collect_google_form_links(self, folder_id: str) -> list[dict[str, str]]:
        """
        Collect Google Forms using rclone lsjson.
        """
        cmd = [
            "rclone", "lsjson", f"{RCLONE_REMOTE_NAME}:",
            "--drive-root-folder-id", folder_id,
            "--recursive",
            "--files-only",
            "--include", "*.gform",
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        ]
        
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd, capture_output=True, check=True
            )
            import json
            items = json.loads(result.stdout)
            
            forms = []
            for item in items:
                forms.append({
                    "id": item["ID"],
                    "name": item["Name"],
                    "path": item["Path"],
                    "mime_type": item["MimeType"]
                })
            return forms
        except Exception as e:
            logger.error("Failed to collect forms", error=str(e))
            return []

    async def register_google_forms_to_db(self, db: AsyncSession, forms: list[dict[str, str]]) -> dict[str, Any]:
        """
        Register Google Forms to DB.
        """
        count = 0
        for form in forms:
            # Check duplicate
            exists = await db.execute(select(Document).where(Document.drive_id == form["id"]))
            if exists.scalar():
                continue
                
            doc = Document(
                drive_id=form["id"],
                drive_name=form["name"],
                drive_path=form["path"],
                mime_type="application/vnd.google-apps.form",
                doc_type=DocumentType.OTHER,
                status=DocumentStatus.COMPLETED, # Forms are links, treated as complete
                doc_metadata={"source": "rclone_lsjson"}
            )
            db.add(doc)
            count += 1
        
        await db.commit()
        return {"new_forms": count}

    # =========================================================================

    async def run_step1(
        self,
        db: AsyncSession,
        folder_id: str | None = None,
        skip_sync: bool = False,
    ) -> dict[str, Any]:
        """
        Execute full Step 1 pipeline: rclone sync + Forms collection + DB registration.
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
                logger.info("[STEP1] Starting rclone sync", folder_id=folder_id)
                sync_result = await self.sync_from_drive(folder_id)
                result["sync"] = {
                    "files_synced": sync_result.files_synced,
                    "files_failed": sync_result.files_failed,
                    "errors": sync_result.errors[:5] if sync_result.errors else [],
                }
            else:
                logger.info("[STEP1] Skipping rclone sync")
                result["sync"] = {"skipped": True}

            # Step 1b: Collect Google Forms URLs
            if folder_id:
                try:
                    forms = await self.collect_google_form_links(folder_id)
                    forms_result = await self.register_google_forms_to_db(db, forms)
                    result["forms"] = forms_result
                except Exception as e:
                    logger.warning("[STEP1] Failed to collect Google Forms", error=str(e))
                    result["forms"] = {"error": str(e)}
            else:
                result["forms"] = {"skipped": True}

            # Step 1c: Fetch Metadata & Register Files
            logger.info("[STEP1] Fetching metadata and registering local files")
            
            drive_map = {}
            if folder_id:
                drive_map = await self._fetch_drive_metadata(folder_id)
                
            files = self.scan_local_files()
            files_result = await self.register_files_to_db(db, files, drive_id_map=drive_map)
            
            result["files"] = {
                "scanned": len(files),
                "new": files_result["new"],
                "skipped": files_result["skipped"],
            }

            result["success"] = True
            logger.info("[STEP1] Step 1 completed successfully")

        except Exception as e:
            logger.exception("[STEP1] Step 1 failed", error=str(e))
            result["error"] = str(e)
            raise

        return result
