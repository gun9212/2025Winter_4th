"""Google Drive service for file operations."""

import io
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.core.security import get_google_credentials
from app.models.document import DocumentType

# Google MIME Type to DocumentType mapping
MIME_TYPE_MAPPING: dict[str, DocumentType] = {
    "application/vnd.google-apps.document": DocumentType.GOOGLE_DOC,
    "application/vnd.google-apps.spreadsheet": DocumentType.GOOGLE_SHEET,
    "application/vnd.google-apps.form": DocumentType.GOOGLE_FORM,
    "application/pdf": DocumentType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.DOCX,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentType.XLSX,
    "application/msword": DocumentType.DOCX,
    "application/vnd.ms-excel": DocumentType.XLSX,
}

# Google Forms MIME type (external link only, no download)
GOOGLE_FORM_MIME_TYPE = "application/vnd.google-apps.form"

# Supported MIME types for ingestion (excluding Google Forms - handled separately)
SUPPORTED_MIME_TYPES: list[str] = [
    mime for mime in MIME_TYPE_MAPPING.keys()
    if mime != GOOGLE_FORM_MIME_TYPE
]


def get_document_type(mime_type: str) -> DocumentType:
    """Convert Google MIME type to DocumentType enum."""
    return MIME_TYPE_MAPPING.get(mime_type, DocumentType.OTHER)


class GoogleDriveService:
    """Service for interacting with Google Drive API."""

    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        """Get or create Drive service instance."""
        if self._service is None:
            credentials = get_google_credentials()
            self._service = build("drive", "v3", credentials=credentials)
        return self._service

    def list_files(
        self,
        folder_id: str,
        page_size: int = 100,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        List files in a Google Drive folder.

        Args:
            folder_id: The folder ID to list files from.
            page_size: Maximum number of files to return per page.
            file_types: Optional list of MIME types to filter.

        Returns:
            List of file metadata dictionaries.
        """
        query = f"'{folder_id}' in parents and trashed = false"

        if file_types:
            type_queries = [f"mimeType = '{t}'" for t in file_types]
            query += f" and ({' or '.join(type_queries)})"

        files = []
        page_token = None

        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)",
                    pageSize=page_size,
                    pageToken=page_token,
                )
                .execute()
            )

            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")

            if not page_token:
                break

        return files

    def list_files_recursive(
        self,
        folder_id: str,
        file_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Recursively list all files in a folder and its subfolders.

        Args:
            folder_id: The root folder ID.
            file_types: Optional list of MIME types to filter.

        Returns:
            List of all file metadata dictionaries.
        """
        all_files = []

        # Get files in current folder
        files = self.list_files(folder_id, file_types=file_types)
        all_files.extend(files)

        # Get subfolders
        subfolders = self.list_files(
            folder_id, file_types=["application/vnd.google-apps.folder"]
        )

        # Recursively process subfolders
        for folder in subfolders:
            subfolder_files = self.list_files_recursive(
                folder["id"], file_types=file_types
            )
            all_files.extend(subfolder_files)

        return all_files

    def download_file(self, file_id: str) -> bytes:
        """
        Download a file from Google Drive.

        Args:
            file_id: The file ID to download.

        Returns:
            File content as bytes.
        """
        request = self.service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        return buffer.read()

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """
        Export a Google Workspace file to a different format.

        Args:
            file_id: The file ID to export.
            mime_type: The target MIME type.

        Returns:
            Exported file content as bytes.
        """
        request = self.service.files().export_media(
            fileId=file_id, mimeType=mime_type
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        return buffer.read()

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        """
        Get metadata for a file.

        Args:
            file_id: The file ID.

        Returns:
            File metadata dictionary.
        """
        return (
            self.service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, modifiedTime, size, parents",
            )
            .execute()
        )

    def list_files_in_folder(
        self,
        folder_id: str,
        recursive: bool = True,
        supported_only: bool = True,
    ) -> list[dict[str, Any]]:
        """
        List files in a folder with DocumentType mapping.

        Args:
            folder_id: Google Drive folder ID.
            recursive: Whether to include subfolders.
            supported_only: Filter to only supported MIME types.

        Returns:
            List of file dictionaries with 'doc_type' field added.
        """
        file_types = SUPPORTED_MIME_TYPES if supported_only else None

        if recursive:
            files = self.list_files_recursive(folder_id, file_types=file_types)
        else:
            files = self.list_files(folder_id, file_types=file_types)

        # Add doc_type field to each file
        for file in files:
            file["doc_type"] = get_document_type(file.get("mimeType", ""))

        return files

    def list_google_forms(
        self,
        folder_id: str,
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """
        List Google Forms in a folder with their webViewLink URLs.

        Google Forms cannot be downloaded, so we only collect their URLs
        for reference in the knowledge base.

        Args:
            folder_id: Google Drive folder ID.
            recursive: Whether to include subfolders.

        Returns:
            List of Google Form dictionaries with 'webViewLink' and 'doc_type'.
        """
        file_types = [GOOGLE_FORM_MIME_TYPE]

        if recursive:
            forms = self.list_files_recursive(folder_id, file_types=file_types)
        else:
            forms = self.list_files(folder_id, file_types=file_types)

        # Add doc_type and ensure webViewLink exists
        for form in forms:
            form["doc_type"] = DocumentType.GOOGLE_FORM
            # webViewLink is included in the API response fields

        return forms

    def list_all_files_with_forms(
        self,
        folder_id: str,
        recursive: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """
        List all files including Google Forms, separated by type.

        Args:
            folder_id: Google Drive folder ID.
            recursive: Whether to include subfolders.

        Returns:
            Dictionary with 'files' (downloadable) and 'forms' (link only).
        """
        # Get regular files (downloadable)
        files = self.list_files_in_folder(
            folder_id=folder_id,
            recursive=recursive,
            supported_only=True,
        )

        # Get Google Forms (link only)
        forms = self.list_google_forms(
            folder_id=folder_id,
            recursive=recursive,
        )

        return {
            "files": files,
            "forms": forms,
        }
