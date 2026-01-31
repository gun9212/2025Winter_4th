"""Step 1: Ingestion - Collect documents from Google Drive via rclone.

This module handles the initial document collection from Google Drive
to Google Cloud Storage using rclone for efficient batch synchronization.

Note for Mac team member:
    - File encoding issues (NFC/NFD) may occur on macOS
    - Use rclone with --drive-encoding option for compatibility
    - Ensure UTF-8 normalization for Korean filenames
"""

import asyncio
import os
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings

logger = structlog.get_logger()


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
                     Defaults to /tmp/council-ai/ingestion
        """
        self.work_dir = Path(work_dir or "/tmp/council-ai/ingestion")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.gcs_bucket = settings.GCS_BUCKET_NAME

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
        import shutil
        target = Path(directory) if directory else self.work_dir
        if target.exists():
            shutil.rmtree(target)
            logger.info("Cleaned up ingestion directory", path=str(target))
