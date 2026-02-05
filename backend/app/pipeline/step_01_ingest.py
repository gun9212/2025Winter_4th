"""Step 1: Ingestion - Collect documents from Google Drive via rclone.

This module handles the initial document collection from Google Drive
to Google Cloud Storage using rclone for efficient batch synchronization.
"""

import asyncio
import os
import shutil
import subprocess
import unicodedata
import json  # Added missing import
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentStatus, DocumentType

logger = structlog.get_logger()

# =============================================================================
# Constants
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
    # Google native formats
    ".gdoc": DocumentType.GOOGLE_DOC,
    ".gsheet": DocumentType.GOOGLE_SHEET,
    ".gslides": DocumentType.OTHER,
    "": DocumentType.GOOGLE_DOC,
}

SUPPORTED_EXTENSIONS: set[str] = {
    ".docx", ".xlsx", ".pptx", ".pdf",
    ".hwp", ".hwpx", ".txt", ".csv",
    ".jpg", ".jpeg", ".png",
    ".gdoc", ".gsheet", ".gslides",
    "",
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
    """

    def __init__(self, work_dir: str | None = None):
        self.work_dir = Path(work_dir or settings.DATA_RAW_PATH or "/tmp/council-ai/ingestion")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.gcs_bucket = settings.GCS_BUCKET_NAME
        self.processed_path = Path(settings.DATA_PROCESSED_PATH or "/app/data/processed")
        self.processed_path.mkdir(parents=True, exist_ok=True)

    def normalize_filename(self, filename: str) -> str:
        """Normalize filename to NFC form for cross-platform compatibility."""
        return unicodedata.normalize("NFC", filename)

    async def _fetch_drive_metadata(self, drive_folder_id: str) -> dict[str, dict[str, str]]:
        """Fetch metadata (IDs and Names) for all files in the Drive folder."""
        logger.info("[METADATA] Fetching Drive IDs via rclone lsjson", folder_id=drive_folder_id)
        
        cmd = [
            "rclone", "lsjson", "gdrive:",
            "--drive-root-folder-id", drive_folder_id,
            "--recursive", "--files-only", "--no-mimetype", "--no-modtime",
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            "--drive-skip-shortcuts", 
        ]
        
        try:
            result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, check=True)
            items = json.loads(result.stdout)
            
            drive_map: dict[str, dict[str, str]] = {}
            for item in items:
                path = item["Path"]
                drive_id = item["ID"]
                name = item["Name"]
                norm_path = self.normalize_filename(path)
                
                # Default mapping
                drive_map[norm_path] = {"id": drive_id, "name": name}
                
                # Handle Exported formats mapping
                ext = os.path.splitext(name)[1].lower()
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

    async def list_synced_files(self, folder_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        [COMPATIBILITY FIX] Wrapper for Task Runner.
        task/pipeline.py expects this method to exist and be async.
        """
        # scan_local_files is synchronous, so we just call it.
        # If it becomes heavy, wrap in asyncio.to_thread
        return self.scan_local_files()

    def scan_local_files(self) -> list[dict[str, Any]]:
        """Scan local directory for supported files."""
        files = []
        for root, _, filenames in os.walk(self.work_dir):
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                
                if ext == "":
                    ext = ".gdoc"

                full_path = Path(root) / filename
                try:
                    rel_path = str(full_path.relative_to(self.work_dir))
                    
                    # [FIXED] SyntaxError fixed here (.isoformat())
                    files.append({
                        "path": rel_path,
                        "full_path": str(full_path),
                        "name": filename,
                        "extension": ext,
                        "size": full_path.stat().st_size,
                        "modified_time": datetime.fromtimestamp(full_path.stat().st_mtime).isoformat(),
                        "doc_type": EXTENSION_TO_DOCTYPE.get(ext, DocumentType.OTHER),
                    })
                except Exception as e:
                    logger.warning(f"Skipping file {filename}: {e}")
                    continue
        return files

    async def register_files_to_db(
        self,
        db: AsyncSession,
        files: list[dict[str, Any]] | None = None,
        drive_id_map: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """Register scanned files to the database."""
        if files is None:
            files = self.scan_local_files()
            
        logger.info("[REGISTER] Starting file registration", files_to_process=len(files), has_id_map=bool(drive_id_map))

        existing_result = await db.execute(select(Document.drive_id))
        existing_ids = set(row[0] for row in existing_result.fetchall() if row[0])

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]
            drive_meta = drive_id_map.get(file_path) if drive_id_map else None
            
            if drive_meta and isinstance(drive_meta, dict):
                drive_id = drive_meta.get("id", f"local:{file_path}")
                file_name = drive_meta.get("name") or file_info.get("name", "Untitled")
            elif drive_meta and isinstance(drive_meta, str):
                drive_id = drive_meta
                file_name = file_info.get("name", "Untitled")
            else:
                drive_id = f"local:{file_path}"
                file_name = file_info.get("name", "Untitled")
                if drive_id_map:
                    logger.warning("[REGISTER] ID not found in map, using local", path=file_path)

            if drive_id in existing_ids:
                skipped_count += 1
                logger.debug("[REGISTER] Skipping duplicate", drive_id=drive_id)
                continue

            doc = Document(
                drive_id=drive_id,
                drive_name=file_name,
                drive_path=file_info["path"],
                mime_type=_get_mime_type(file_info["extension"]),
                doc_type=file_info["doc_type"],
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "full_path": file_info["full_path"],
                    "size": file_info["size"],
                    "modified_time": file_info["modified_time"],
                    "source": "rclone_sync",
                    "original_path": file_info["path"],
                },
            )
            db.add(doc)
            existing_ids.add(drive_id)
            new_count += 1
            
            logger.debug("[REGISTER] Added new document", drive_id=drive_id, name=file_name)

        await db.commit()
        logger.info("[REGISTER] Registration completed", new=new_count, skipped=skipped_count, total=len(files))
        return {"new": new_count, "skipped": skipped_count, "total": len(files)}

    async def sync_from_drive(self, folder_id: str) -> IngestionResult:
        """Sync files from Google Drive to local storage using rclone."""
        logger.info("[SYNC] Starting rclone sync", folder_id=folder_id)
        
        source = f"{RCLONE_REMOTE_NAME}:{folder_id}"
        dest = str(self.work_dir)
        
        cmd = [
            "rclone", "sync", source, dest,
            "--drive-export-formats", RCLONE_EXPORT_FORMATS,
            "--drive-root-folder-id", folder_id,
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            "--create-empty-src-dirs=false", "--drive-skip-shortcuts", "-v",
        ]
        
        for pattern in RCLONE_INCLUDE_PATTERNS:
            cmd.extend(["--include", pattern])
        for pattern in RCLONE_EXCLUDE_PATTERNS:
            cmd.extend(["--exclude", pattern])

        try:
            process = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, check=True)
            return IngestionResult(files_synced=0, files_failed=0, total_size_bytes=0, sync_log=[process.stderr], errors=[])
        except subprocess.CalledProcessError as e:
            logger.error("[SYNC] Rclone failed", error=e.stderr)
            return IngestionResult(files_synced=0, files_failed=1, total_size_bytes=0, sync_log=[], errors=[e.stderr])

    async def collect_google_form_links(self, folder_id: str) -> list[dict[str, str]]:
        """Collect Google Forms using rclone lsjson."""
        cmd = [
            "rclone", "lsjson", f"{RCLONE_REMOTE_NAME}:",
            "--drive-root-folder-id", folder_id,
            "--recursive", "--files-only", "--include", "*.gform",
            "--drive-service-account-file", os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
        ]
        try:
            result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, check=True)
            items = json.loads(result.stdout)
            return [{"id": i["ID"], "name": i["Name"], "path": i["Path"], "mime_type": i["MimeType"]} for i in items]
        except Exception as e:
            logger.error("Failed to collect forms", error=str(e))
            return []

    async def register_google_forms_to_db(self, db: AsyncSession, forms: list[dict[str, str]]) -> dict[str, Any]:
        """Register Google Forms to DB."""
        count = 0
        for form in forms:
            exists = await db.execute(select(Document).where(Document.drive_id == form["id"]))
            if exists.scalar():
                continue
            doc = Document(
                drive_id=form["id"],
                drive_name=form["name"],
                drive_path=form["path"],
                mime_type="application/vnd.google-apps.form",
                doc_type=DocumentType.OTHER,
                status=DocumentStatus.COMPLETED,
                doc_metadata={"source": "rclone_lsjson"}
            )
            db.add(doc)
            count += 1
        await db.commit()
        return {"new_forms": count}

    async def run_step1(self, db: AsyncSession, folder_id: str | None = None, skip_sync: bool = False) -> dict[str, Any]:
        """Execute full Step 1 pipeline."""
        folder_id = folder_id or settings.GOOGLE_DRIVE_FOLDER_ID or ""
        result: dict[str, Any] = {"folder_id": folder_id, "sync": None, "forms": None, "files": None, "success": False}

        try:
            if not skip_sync and folder_id:
                logger.info("[STEP1] Starting rclone sync", folder_id=folder_id)
                sync_result = await self.sync_from_drive(folder_id)
                result["sync"] = {"files_synced": sync_result.files_synced, "errors": sync_result.errors}
            else:
                result["sync"] = {"skipped": True}

            if folder_id:
                forms = await self.collect_google_form_links(folder_id)
                result["forms"] = await self.register_google_forms_to_db(db, forms)
            else:
                result["forms"] = {"skipped": True}

            logger.info("[STEP1] Fetching metadata and registering local files")
            drive_map = await self._fetch_drive_metadata(folder_id) if folder_id else {}
            files = self.scan_local_files()
            files_result = await self.register_files_to_db(db, files, drive_id_map=drive_map)
            
            result["files"] = {"scanned": len(files), "new": files_result["new"], "skipped": files_result["skipped"]}
            result["success"] = True
            logger.info("[STEP1] Step 1 completed successfully")

        except Exception as e:
            logger.exception("[STEP1] Step 1 failed", error=str(e))
            result["error"] = str(e)
            raise

        return result