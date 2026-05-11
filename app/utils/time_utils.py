from datetime import datetime, timedelta


def add_minutes(time_text: str, minutes: int) -> str:
    base = datetime.strptime(time_text, "%H:%M")
    return (base + timedelta(minutes=minutes)).strftime("%H:%M")

