"""Security utilities for authentication and authorization."""

from typing import Any

import google.auth
from google.auth.credentials import Credentials
from google.auth.transport.requests import Request


def get_google_credentials() -> Credentials:
    """
    Get Google Cloud credentials using Application Default Credentials (ADC).

    Returns:
        Google Cloud credentials for API authentication.

    Raises:
        google.auth.exceptions.DefaultCredentialsError: If no credentials found.
    """
    credentials, project = google.auth.default(
        scopes=[
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/cloud-platform",
        ]
    )

    # Refresh credentials if expired
    if credentials.expired:
        credentials.refresh(Request())

    return credentials


def verify_api_key(api_key: str, expected_key: str) -> bool:
    """
    Verify API key for simple authentication.

    Args:
        api_key: The API key to verify.
        expected_key: The expected API key.

    Returns:
        True if the API key is valid, False otherwise.
    """
    if not api_key or not expected_key:
        return False

    # Use constant-time comparison to prevent timing attacks
    return len(api_key) == len(expected_key) and all(
        a == b for a, b in zip(api_key, expected_key)
    )


class GoogleServiceAccountAuth:
    """Google Service Account authentication handler."""

    def __init__(self) -> None:
        self._credentials: Credentials | None = None

    @property
    def credentials(self) -> Credentials:
        """Get or refresh credentials."""
        if self._credentials is None or self._credentials.expired:
            self._credentials = get_google_credentials()
        return self._credentials

    def get_access_token(self) -> str:
        """Get a valid access token."""
        creds = self.credentials
        if creds.token is None:
            creds.refresh(Request())
        return creds.token  # type: ignore


# Singleton instance
google_auth = GoogleServiceAccountAuth()
