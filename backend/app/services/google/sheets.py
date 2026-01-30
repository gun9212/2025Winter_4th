"""Google Sheets service for spreadsheet operations."""

from typing import Any

from googleapiclient.discovery import build

from app.core.security import get_google_credentials


class GoogleSheetsService:
    """Service for interacting with Google Sheets API."""

    def __init__(self) -> None:
        self._service = None

    @property
    def service(self):
        """Get or create Sheets service instance."""
        if self._service is None:
            credentials = get_google_credentials()
            self._service = build("sheets", "v4", credentials=credentials)
        return self._service

    def get_spreadsheet(self, spreadsheet_id: str) -> dict[str, Any]:
        """
        Get spreadsheet metadata.

        Args:
            spreadsheet_id: The spreadsheet ID.

        Returns:
            Spreadsheet metadata.
        """
        return (
            self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        )

    def get_sheet_names(self, spreadsheet_id: str) -> list[str]:
        """
        Get all sheet names in a spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID.

        Returns:
            List of sheet names.
        """
        spreadsheet = self.get_spreadsheet(spreadsheet_id)
        return [sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])]

    def read_range(
        self,
        spreadsheet_id: str,
        range_notation: str,
        value_render_option: str = "FORMATTED_VALUE",
    ) -> list[list[Any]]:
        """
        Read values from a specified range.

        Args:
            spreadsheet_id: The spreadsheet ID.
            range_notation: A1 notation range (e.g., "Sheet1!A1:D10").
            value_render_option: How values should be rendered.

        Returns:
            2D list of cell values.
        """
        result = (
            self.service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueRenderOption=value_render_option,
            )
            .execute()
        )

        return result.get("values", [])

    def read_all_sheets(self, spreadsheet_id: str) -> dict[str, list[list[Any]]]:
        """
        Read all data from all sheets in a spreadsheet.

        Args:
            spreadsheet_id: The spreadsheet ID.

        Returns:
            Dictionary mapping sheet names to their data.
        """
        sheet_names = self.get_sheet_names(spreadsheet_id)
        all_data = {}

        for name in sheet_names:
            data = self.read_range(spreadsheet_id, f"'{name}'")
            all_data[name] = data

        return all_data

    def write_range(
        self,
        spreadsheet_id: str,
        range_notation: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """
        Write values to a specified range.

        Args:
            spreadsheet_id: The spreadsheet ID.
            range_notation: A1 notation range.
            values: 2D list of values to write.
            value_input_option: How input should be interpreted.

        Returns:
            Update response.
        """
        return (
            self.service.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                body={"values": values},
            )
            .execute()
        )

    def append_rows(
        self,
        spreadsheet_id: str,
        range_notation: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        """
        Append rows to the end of a range.

        Args:
            spreadsheet_id: The spreadsheet ID.
            range_notation: A1 notation range (sheet name).
            values: 2D list of values to append.
            value_input_option: How input should be interpreted.

        Returns:
            Append response.
        """
        return (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_notation,
                valueInputOption=value_input_option,
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
            .execute()
        )

    def create_spreadsheet(self, title: str) -> dict[str, Any]:
        """
        Create a new spreadsheet.

        Args:
            title: The spreadsheet title.

        Returns:
            Created spreadsheet metadata.
        """
        return (
            self.service.spreadsheets()
            .create(body={"properties": {"title": title}})
            .execute()
        )
