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
        Scan local data directory for synced files recursively.

        Returns:
            List of file metadata dictionaries.
        """
        files = []

        logger.info(
            "=== [SCAN] Starting recursive file scan ===",
            data_path=str(self.data_path),
            exists=self.data_path.exists(),
        )

        if not self.data_path.exists():
            logger.warning("[SCAN] Data path does not exist", path=str(self.data_path))
            return files

        # List all subdirectories first for debugging
        subdirs = [d for d in self.data_path.rglob("*") if d.is_dir()]
        logger.info(
            "[SCAN] Found subdirectories",
            count=len(subdirs),
            dirs=[str(d.relative_to(self.data_path)) for d in subdirs],
        )

        # Scan all files recursively using rglob
        all_items = list(self.data_path.rglob("*"))
        file_items = [f for f in all_items if f.is_file()]
        logger.info(
            "[SCAN] Total items breakdown",
            total_items=len(all_items),
            files_only=len(file_items),
            directories=len(all_items) - len(file_items),
        )

        for file_path in file_items:
            extension = file_path.suffix.lower()
            relative_path = str(file_path.relative_to(self.data_path))

            # Log every file found (including unsupported)
            logger.info(
                "[SCAN] Found file",
                relative_path=relative_path,
                full_path=str(file_path),
                extension=extension,
                supported=extension in SUPPORTED_EXTENSIONS,
            )

            if extension not in SUPPORTED_EXTENSIONS:
                logger.info(
                    "[SCAN] Skipping unsupported file",
                    path=relative_path,
                    extension=extension,
                )
                continue

            stat = file_path.stat()

            file_info = {
                "name": file_path.name,
                "path": relative_path,
                "full_path": str(file_path),
                "extension": extension,
                "doc_type": EXTENSION_TO_DOCTYPE.get(extension, DocumentType.OTHER),
                "size": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            }
            files.append(file_info)

            logger.info(
                "[SCAN] Added file to results",
                name=file_path.name,
                relative_path=relative_path,
                doc_type=file_info["doc_type"].value if hasattr(file_info["doc_type"], 'value') else str(file_info["doc_type"]),
                size_bytes=stat.st_size,
            )

        logger.info(
            "=== [SCAN] File scan completed ===",
            total_files=len(files),
            by_extension={ext: sum(1 for f in files if f["extension"] == ext) for ext in set(f["extension"] for f in files)} if files else {},
        )

        return files

    async def sync_folder_to_db(
        self,
        db: AsyncSession,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Sync files from data/raw folder to DB.

        This method ensures all files in the raw directory are registered
        in the database with PENDING status. Call this before parsing
        to ensure the DB is in sync with the filesystem.

        Args:
            db: Database session.
            force: If True, scan and register even if DB is not empty.

        Returns:
            Dictionary with sync results.
        """
        logger.info("=== [DB SYNC] Starting folder-to-DB sync ===")

        # Check if DB has any documents
        doc_count_result = await db.execute(
            select(Document.id).limit(1)
        )
        db_has_docs = doc_count_result.scalar() is not None

        if db_has_docs and not force:
            logger.info("[DB SYNC] DB already has documents, skipping sync (use force=True to override)")
            return {
                "synced": False,
                "reason": "DB already has documents",
                "new": 0,
                "skipped": 0,
                "total": 0,
            }

        # Scan files from filesystem
        logger.info("[DB SYNC] Scanning filesystem for files...")
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

        # Register files to DB
        logger.info(f"[DB SYNC] Registering {len(files)} files to DB...")
        result = await self.register_files_to_db(db, files)

        logger.info(
            "=== [DB SYNC] Folder-to-DB sync completed ===",
            new=result["new"],
            skipped=result["skipped"],
            total=result["total"],
        )

        return {
            "synced": True,
            "reason": "Files registered",
            **result,
        }

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
            Dictionary with new, skipped, and total counts.
        """
        logger.info(
            "[REGISTER] Starting file registration",
            files_to_process=len(files),
        )

        # 1. 기존 DB에 등록된 '경로'들을 싹 가져와서 중복 검사 준비
        existing_result = await db.execute(select(Document.drive_path))
        existing_paths = set(row[0] for row in existing_result.fetchall() if row[0])

        logger.info(
            "[REGISTER] Existing paths in DB",
            count=len(existing_paths),
            paths=list(existing_paths)[:10],  # 처음 10개만 로깅
        )

        new_count = 0
        skipped_count = 0

        for file_info in files:
            file_path = file_info["path"]  # '1차 회의/안건지.pdf' 형태의 상대경로

            # 중복 체크
            if file_path in existing_paths:
                logger.info(
                    "[REGISTER] Skipping duplicate",
                    path=file_path,
                )
                skipped_count += 1
                continue

            # 중요: drive_id를 경로 기반으로 생성하여 유니크하게 관리
            drive_id = f"local:{file_path}"

            doc = Document(
                drive_id=drive_id,
                drive_name=file_info["name"],
                drive_path=file_path,  # 하위 폴더 포함 경로 저장
                mime_type=self._get_mime_type(file_info["extension"]),
                doc_type=file_info["doc_type"],
                status=DocumentStatus.PENDING,
                doc_metadata={
                    "full_path": file_info["full_path"],  # 실제 VM 내 절대 경로
                    "size": file_info["size"],
                    "modified_time": file_info["modified_time"],
                    "source": "rclone_sync",
                },
            )
            db.add(doc)
            new_count += 1

            logger.info(
                "[REGISTER] Added new document",
                drive_id=drive_id,
                drive_path=file_path,
                full_path=file_info["full_path"],
                doc_type=file_info["doc_type"].value if hasattr(file_info["doc_type"], 'value') else str(file_info["doc_type"]),
            )

        await db.commit()

        logger.info(
            "[REGISTER] Registration completed",
            new=new_count,
            skipped=skipped_count,
            total=len(files),
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
        auto_sync: bool = True,
    ) -> dict[str, Any]:
        """
        Parse pending documents using Upstage Parser and update DB.

        This method will automatically sync files from data/raw to DB
        if there are no pending documents (auto_sync=True).

        Args:
            db: Database session.
            limit: Maximum number of documents to parse.
            auto_sync: If True, sync files to DB first if no pending docs.

        Returns:
            Dictionary with parsing results.
        """
        from app.services.parser.upstage import UpstageDocParser, UpstageParserError

        logger.info(
            "=== [PARSE] Starting document parsing ===",
            limit=limit,
            auto_sync=auto_sync,
        )

        parser = UpstageDocParser(
            raw_data_path=str(self.data_path),
            processed_data_path=str(self.processed_path),
        )

        # Check if DB has pending documents
        pending_check = await db.execute(
            select(Document.id)
            .where(Document.status == DocumentStatus.PENDING)
            .where(Document.doc_type != DocumentType.GOOGLE_FORM)
            .limit(1)
        )
        has_pending = pending_check.scalar() is not None

        # If no pending documents and auto_sync is enabled, sync files first
        if not has_pending and auto_sync:
            logger.info("[PARSE] No pending documents found, syncing files from folder...")
            sync_result = await self.sync_folder_to_db(db, force=True)
            logger.info(
                "[PARSE] Folder sync result",
                new=sync_result.get("new", 0),
                total=sync_result.get("total", 0),
            )

        # Get pending documents
        result = await db.execute(
            select(Document)
            .where(Document.status == DocumentStatus.PENDING)
            .where(Document.doc_type != DocumentType.GOOGLE_FORM)
            .limit(limit)
        )
        pending_docs = result.scalars().all()

        logger.info(
            "[PARSE] Found pending documents",
            count=len(pending_docs),
            docs=[{"id": d.id, "name": d.drive_name, "path": d.drive_path} for d in pending_docs],
        )

        results = {
            "success": [],
            "failed": [],
            "total": len(pending_docs),
        }

        if len(pending_docs) == 0:
            logger.warning("[PARSE] No pending documents to parse")
            return results

        for doc in pending_docs:
            file_path = doc.doc_metadata.get("full_path") if doc.doc_metadata else None

            logger.info(
                "[PARSE] Processing document",
                doc_id=doc.id,
                name=doc.drive_name,
                drive_path=doc.drive_path,
                full_path=file_path,
            )

            if not file_path:
                logger.error(
                    "[PARSE] No file path in metadata",
                    doc_id=doc.id,
                    name=doc.drive_name,
                    metadata=doc.doc_metadata,
                )
                results["failed"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "error": "No file path in metadata",
                })
                continue

            # Verify file exists
            if not Path(file_path).exists():
                logger.error(
                    "[PARSE] File does not exist on filesystem",
                    doc_id=doc.id,
                    full_path=file_path,
                )
                results["failed"].append({
                    "id": doc.id,
                    "name": doc.drive_name,
                    "error": f"File not found: {file_path}",
                })
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"File not found: {file_path}"
                await db.commit()
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
