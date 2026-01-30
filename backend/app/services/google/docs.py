"""Google Docs service for document operations."""

from typing import Any

from googleapiclient.discovery import build

from app.core.security import get_google_credentials


class GoogleDocsService:
    """Service for interacting with Google Docs API."""

    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        """Get or create Docs service instance."""
        if self._service is None:
            credentials = get_google_credentials()
            self._service = build("docs", "v1", credentials=credentials)
        return self._service

    def get_document(self, document_id: str) -> dict[str, Any]:
        """
        Get a Google Docs document.

        Args:
            document_id: The document ID.

        Returns:
            Document content and metadata.
        """
        return self.service.documents().get(documentId=document_id).execute()

    def get_document_text(self, document_id: str) -> str:
        """
        Extract plain text from a Google Docs document.

        Args:
            document_id: The document ID.

        Returns:
            Plain text content of the document.
        """
        doc = self.get_document(document_id)
        content = doc.get("body", {}).get("content", [])

        text_parts = []
        for element in content:
            if "paragraph" in element:
                for para_element in element["paragraph"].get("elements", []):
                    if "textRun" in para_element:
                        text_parts.append(para_element["textRun"].get("content", ""))
            elif "table" in element:
                # Extract text from tables
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        for cell_content in cell.get("content", []):
                            if "paragraph" in cell_content:
                                for para_element in cell_content["paragraph"].get(
                                    "elements", []
                                ):
                                    if "textRun" in para_element:
                                        text_parts.append(
                                            para_element["textRun"].get("content", "")
                                        )

        return "".join(text_parts)

    def create_document(self, title: str) -> dict[str, Any]:
        """
        Create a new Google Docs document.

        Args:
            title: The document title.

        Returns:
            Created document metadata.
        """
        return self.service.documents().create(body={"title": title}).execute()

    def batch_update(
        self, document_id: str, requests: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Apply batch updates to a document.

        Args:
            document_id: The document ID.
            requests: List of update request objects.

        Returns:
            Batch update response.
        """
        return (
            self.service.documents()
            .batchUpdate(documentId=document_id, body={"requests": requests})
            .execute()
        )

    def replace_text(
        self, document_id: str, replacements: dict[str, str]
    ) -> dict[str, Any]:
        """
        Replace placeholder text in a document.

        Args:
            document_id: The document ID.
            replacements: Dictionary of placeholder -> replacement text.

        Returns:
            Batch update response.
        """
        requests = [
            {
                "replaceAllText": {
                    "containsText": {"text": placeholder, "matchCase": True},
                    "replaceText": replacement,
                }
            }
            for placeholder, replacement in replacements.items()
        ]

        return self.batch_update(document_id, requests)

    def insert_text(
        self, document_id: str, text: str, index: int = 1
    ) -> dict[str, Any]:
        """
        Insert text at a specific index in the document.

        Args:
            document_id: The document ID.
            text: Text to insert.
            index: Character index to insert at (1 = beginning).

        Returns:
            Batch update response.
        """
        requests = [{"insertText": {"location": {"index": index}, "text": text}}]

        return self.batch_update(document_id, requests)

    def copy_document(self, document_id: str, new_title: str) -> dict[str, Any]:
        """
        Create a copy of a document (uses Drive API).

        Args:
            document_id: The source document ID.
            new_title: Title for the new document.

        Returns:
            New document metadata.
        """
        from googleapiclient.discovery import build

        credentials = get_google_credentials()
        drive_service = build("drive", "v3", credentials=credentials)

        return (
            drive_service.files()
            .copy(fileId=document_id, body={"name": new_title})
            .execute()
        )
