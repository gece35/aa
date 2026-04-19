"""JSON-based persistent storage for lessons and repetitions."""
import json
import uuid
from datetime import date
from pathlib import Path
from typing import List, Dict, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "lessons.json"


def _load() -> Dict:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    return {"lessons": []}


def _save(data: Dict) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_lesson(topic: str, subject: str, study_date: str, schedule: List[Dict]) -> Dict:
    data = _load()
    lesson = {
        "id": str(uuid.uuid4())[:8],
        "topic": topic,
        "subject": subject,
        "study_date": study_date,
        "created_at": date.today().isoformat(),
        "schedule": schedule,
        "synced_event_ids": [],
    }
    data["lessons"].append(lesson)
    _save(data)
    return lesson


def get_all_lessons() -> List[Dict]:
    return _load()["lessons"]


def get_lesson(lesson_id: str) -> Optional[Dict]:
    for lesson in _load()["lessons"]:
        if lesson["id"] == lesson_id:
            return lesson
    return None


def update_synced_events(lesson_id: str, event_ids: List[str]) -> None:
    data = _load()
    for lesson in data["lessons"]:
        if lesson["id"] == lesson_id:
            lesson["synced_event_ids"] = event_ids
            break
    _save(data)


def delete_lesson(lesson_id: str) -> bool:
    data = _load()
    before = len(data["lessons"])
    data["lessons"] = [l for l in data["lessons"] if l["id"] != lesson_id]
    if len(data["lessons"]) < before:
        _save(data)
        return True
    return False


def get_upcoming_repetitions(days_ahead: int = 7) -> List[Dict]:
    from datetime import timedelta
    today = date.today()
    cutoff = today + timedelta(days=days_ahead)
    upcoming = []
    for lesson in get_all_lessons():
        for rep in lesson["schedule"]:
            rep_date = date.fromisoformat(rep["date"])
            if today <= rep_date <= cutoff:
                upcoming.append({
                    "lesson_id": lesson["id"],
                    "topic": lesson["topic"],
                    "subject": lesson["subject"],
                    **rep,
                })
    upcoming.sort(key=lambda x: x["date"])
    return upcoming
