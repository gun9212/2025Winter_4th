"""Google Calendar service for event management."""

from datetime import datetime, timedelta
from typing import Any

from googleapiclient.discovery import build

from app.core.security import get_google_credentials


class GoogleCalendarService:
    """Service for interacting with Google Calendar API."""

    def __init__(self, calendar_id: str = "primary") -> None:
        self._service = None
        self.calendar_id = calendar_id

    @property
    def service(self):
        """Get or create Calendar service instance."""
        if self._service is None:
            credentials = get_google_credentials()
            self._service = build("calendar", "v3", credentials=credentials)
        return self._service

    def list_events(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """
        List calendar events within a time range.

        Args:
            time_min: Start of time range (default: now).
            time_max: End of time range (default: 30 days from now).
            max_results: Maximum number of events to return.

        Returns:
            List of event dictionaries.
        """
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=30)

        events_result = (
            self.service.events()
            .list(
                calendarId=self.calendar_id,
                timeMin=time_min.isoformat() + "Z",
                timeMax=time_max.isoformat() + "Z",
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        return events_result.get("items", [])

    def get_event(self, event_id: str) -> dict[str, Any]:
        """
        Get a specific calendar event.

        Args:
            event_id: The event ID.

        Returns:
            Event dictionary.
        """
        return (
            self.service.events()
            .get(calendarId=self.calendar_id, eventId=event_id)
            .execute()
        )

    def create_event(
        self,
        title: str,
        start_time: datetime,
        end_time: datetime,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        reminder_minutes: int = 30,
    ) -> dict[str, Any]:
        """
        Create a new calendar event.

        Args:
            title: Event title/summary.
            start_time: Event start datetime.
            end_time: Event end datetime.
            description: Optional event description.
            location: Optional event location.
            attendees: Optional list of attendee email addresses.
            reminder_minutes: Minutes before event for reminder.

        Returns:
            Created event dictionary.
        """
        event_body: dict[str, Any] = {
            "summary": title,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": "Asia/Seoul",
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": "Asia/Seoul",
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": reminder_minutes},
                ],
            },
        }

        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": email} for email in attendees]

        return (
            self.service.events()
            .insert(calendarId=self.calendar_id, body=event_body)
            .execute()
        )

    def update_event(
        self,
        event_id: str,
        title: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        description: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing calendar event.

        Args:
            event_id: The event ID to update.
            title: New event title.
            start_time: New start datetime.
            end_time: New end datetime.
            description: New description.
            location: New location.

        Returns:
            Updated event dictionary.
        """
        event = self.get_event(event_id)

        if title:
            event["summary"] = title
        if start_time:
            event["start"]["dateTime"] = start_time.isoformat()
        if end_time:
            event["end"]["dateTime"] = end_time.isoformat()
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location

        return (
            self.service.events()
            .update(calendarId=self.calendar_id, eventId=event_id, body=event)
            .execute()
        )

    def delete_event(self, event_id: str) -> None:
        """
        Delete a calendar event.

        Args:
            event_id: The event ID to delete.
        """
        self.service.events().delete(
            calendarId=self.calendar_id, eventId=event_id
        ).execute()

    def quick_add(self, text: str) -> dict[str, Any]:
        """
        Create an event from a text string (natural language).

        Args:
            text: Natural language event description.

        Returns:
            Created event dictionary.
        """
        return (
            self.service.events()
            .quickAdd(calendarId=self.calendar_id, text=text)
            .execute()
        )
