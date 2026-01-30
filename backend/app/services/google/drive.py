"""Google Drive service for file operations."""

import io
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.core.security import get_google_credentials


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
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
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
