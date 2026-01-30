"""Google Cloud Storage service for file storage."""

import io
from typing import Any

from google.cloud import storage

from app.core.config import settings


class GoogleStorageService:
    """Service for interacting with Google Cloud Storage."""

    def __init__(self, bucket_name: str | None = None) -> None:
        self._client = None
        self._bucket = None
        self.bucket_name = bucket_name or settings.GCS_BUCKET_NAME

    @property
    def client(self) -> storage.Client:
        """Get or create Storage client instance."""
        if self._client is None:
            self._client = storage.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        return self._client

    @property
    def bucket(self) -> storage.Bucket:
        """Get or create bucket instance."""
        if self._bucket is None:
            self._bucket = self.client.bucket(self.bucket_name)
        return self._bucket

    def upload_file(
        self,
        file_content: bytes,
        destination_path: str,
        content_type: str | None = None,
    ) -> str:
        """
        Upload a file to GCS.

        Args:
            file_content: File content as bytes.
            destination_path: Path in bucket (e.g., "images/photo.jpg").
            content_type: Optional MIME type.

        Returns:
            GCS URI (gs://bucket/path).
        """
        blob = self.bucket.blob(destination_path)

        if content_type:
            blob.upload_from_string(file_content, content_type=content_type)
        else:
            blob.upload_from_string(file_content)

        return f"gs://{self.bucket_name}/{destination_path}"

    def upload_from_file(
        self,
        file_path: str,
        destination_path: str,
        content_type: str | None = None,
    ) -> str:
        """
        Upload a file from local filesystem to GCS.

        Args:
            file_path: Local file path.
            destination_path: Path in bucket.
            content_type: Optional MIME type.

        Returns:
            GCS URI.
        """
        blob = self.bucket.blob(destination_path)
        blob.upload_from_filename(file_path, content_type=content_type)
        return f"gs://{self.bucket_name}/{destination_path}"

    def download_file(self, source_path: str) -> bytes:
        """
        Download a file from GCS.

        Args:
            source_path: Path in bucket.

        Returns:
            File content as bytes.
        """
        blob = self.bucket.blob(source_path)
        return blob.download_as_bytes()

    def download_to_file(self, source_path: str, destination_path: str) -> None:
        """
        Download a file from GCS to local filesystem.

        Args:
            source_path: Path in bucket.
            destination_path: Local file path.
        """
        blob = self.bucket.blob(source_path)
        blob.download_to_filename(destination_path)

    def get_public_url(self, path: str) -> str:
        """
        Get a public URL for a file.

        Args:
            path: Path in bucket.

        Returns:
            Public URL.
        """
        return f"https://storage.googleapis.com/{self.bucket_name}/{path}"

    def get_signed_url(
        self,
        path: str,
        expiration_minutes: int = 60,
    ) -> str:
        """
        Generate a signed URL for temporary access.

        Args:
            path: Path in bucket.
            expiration_minutes: URL validity period.

        Returns:
            Signed URL.
        """
        from datetime import timedelta

        blob = self.bucket.blob(path)
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )

    def list_files(self, prefix: str = "") -> list[dict[str, Any]]:
        """
        List files in the bucket.

        Args:
            prefix: Path prefix to filter files.

        Returns:
            List of file metadata dictionaries.
        """
        blobs = self.bucket.list_blobs(prefix=prefix)
        return [
            {
                "name": blob.name,
                "size": blob.size,
                "updated": blob.updated,
                "content_type": blob.content_type,
            }
            for blob in blobs
        ]

    def delete_file(self, path: str) -> None:
        """
        Delete a file from GCS.

        Args:
            path: Path in bucket.
        """
        blob = self.bucket.blob(path)
        blob.delete()

    def file_exists(self, path: str) -> bool:
        """
        Check if a file exists in GCS.

        Args:
            path: Path in bucket.

        Returns:
            True if file exists, False otherwise.
        """
        blob = self.bucket.blob(path)
        return blob.exists()
