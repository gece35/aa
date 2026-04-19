"""Google Calendar API integration via google-api-python-client."""
import json
import os
from typing import Dict, List, Optional

CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
TIMEZONE = os.getenv("CALENDAR_TIMEZONE", "Europe/Istanbul")

_service = None


def _get_service():
    global _service
    if _service:
        return _service

    credentials_json = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    if not credentials_json:
        raise RuntimeError(
            "GOOGLE_CALENDAR_CREDENTIALS env var not set. "
            "Set it to the JSON content of your Google service account key."
        )

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds_dict = json.loads(credentials_json)
    scopes = ["https://www.googleapis.com/auth/calendar"]
    credentials = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=scopes
    )
    _service = build("googleapiclient", "v1", credentials=credentials)
    return _service


def is_configured() -> bool:
    return bool(os.getenv("GOOGLE_CALENDAR_CREDENTIALS"))


def create_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    color_id: str = "1",
    recurrence: Optional[List[str]] = None,
) -> Optional[str]:
    """Create a Google Calendar event and return its event ID."""
    try:
        service = _get_service()
        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": TIMEZONE},
            "end": {"dateTime": end_time, "timeZone": TIMEZONE},
            "colorId": color_id,
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 10},
                ],
            },
        }
        if recurrence:
            event_body["recurrence"] = recurrence

        result = service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        return result.get("id")
    except Exception as e:
        print(f"[calendar_api] Error creating event '{summary}': {e}")
        return None


def create_repetition_events(schedule: List[Dict]) -> List[str]:
    """Create all calendar events for a repetition schedule. Returns list of event IDs."""
    event_ids = []
    for rep in schedule:
        eid = create_calendar_event(
            summary=rep["title"],
            start_time=rep["start_time"],
            end_time=rep["end_time"],
            description=rep["description"],
            color_id=rep.get("color_id", "1"),
        )
        if eid:
            event_ids.append(eid)
    return event_ids


def create_weekly_summary_event(
    start_time: str, end_time: str, lessons_summary: str
) -> Optional[str]:
    """Create a weekly summary event on Sunday at 20:00."""
    return create_calendar_event(
        summary="Haftalik Tekrar Ozeti",
        start_time=start_time,
        end_time=end_time,
        description=f"Bu hafta calismalar:\n{lessons_summary}",
        color_id="9",
    )


def delete_calendar_event(event_id: str) -> bool:
    try:
        service = _get_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return True
    except Exception as e:
        print(f"[calendar_api] Error deleting event {event_id}: {e}")
        return False
