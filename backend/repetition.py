"""Spaced repetition scheduling logic."""
from datetime import date, timedelta, datetime
from typing import List, Dict

REPETITION_DAYS = [1, 7, 30, 90]
WEEKDAY_HOUR = 17
WEEKEND_HOUR = 14
TOTAL_REPS = len(REPETITION_DAYS)


def get_notification_hour(d: date) -> int:
    """Return 17 for weekdays, 14 for weekends."""
    return WEEKEND_HOUR if d.weekday() >= 5 else WEEKDAY_HOUR


def calculate_repetition_dates(start_date: date) -> List[date]:
    return [start_date + timedelta(days=d) for d in REPETITION_DAYS]


def format_event_title(topic: str, subject: str, rep_num: int) -> str:
    prefix = f"[{subject}] " if subject else ""
    return f"Tekrar {rep_num}/{TOTAL_REPS}: {prefix}{topic}"


def format_event_description(topic: str, subject: str, rep_num: int, start_date: date) -> str:
    interval_labels = ["1 gün", "1 hafta", "1 ay", "3 ay"]
    return (
        f"Konu: {topic}\n"
        f"Ders: {subject}\n"
        f"İlk çalışma: {start_date.strftime('%d.%m.%Y')}\n"
        f"Bu tekrar: {interval_labels[rep_num - 1]} sonrası ({rep_num}/{TOTAL_REPS})"
    )


def build_repetition_schedule(topic: str, subject: str, start_date: date) -> List[Dict]:
    """Return list of event dicts ready for calendar creation."""
    schedule = []
    for i, rep_date in enumerate(calculate_repetition_dates(start_date), start=1):
        hour = get_notification_hour(rep_date)
        start_dt = datetime(rep_date.year, rep_date.month, rep_date.day, hour, 0, 0)
        end_dt = datetime(rep_date.year, rep_date.month, rep_date.day, hour, 30, 0)
        schedule.append({
            "rep_num": i,
            "date": rep_date.isoformat(),
            "title": format_event_title(topic, subject, i),
            "description": format_event_description(topic, subject, i, start_date),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "color_id": _rep_color(i),
        })
    return schedule


def _rep_color(rep_num: int) -> str:
    """Calendar color IDs per repetition: 1=Lavender,5=Banana,6=Tangerine,11=Tomato."""
    colors = {1: "1", 2: "5", 3: "6", 4: "11"}
    return colors.get(rep_num, "1")


def next_sunday_summary_times() -> Dict:
    """Return start/end ISO strings for next Sunday at 20:00."""
    today = date.today()
    days_until_sunday = (6 - today.weekday()) % 7 or 7
    next_sun = today + timedelta(days=days_until_sunday)
    start = datetime(next_sun.year, next_sun.month, next_sun.day, 20, 0, 0)
    end = datetime(next_sun.year, next_sun.month, next_sun.day, 21, 0, 0)
    return {"start_time": start.isoformat(), "end_time": end.isoformat(), "date": next_sun.isoformat()}
