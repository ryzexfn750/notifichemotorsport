import json
import os
from datetime import datetime, timedelta
from html import escape

import requests
import pytz
from icalendar import Calendar
from dateutil import parser

from config import (
    BOT_TOKEN,
    CHAT_ID,
    F1_ICS_URL,
    MOTOGP_ICS_URL,
    REMIND_BEFORE_MINUTES,
    TIMEZONE
)

SENT_FILE = "sent_events.json"

CALENDARS = [
    {
        "series": "f1",
        "source": F1_ICS_URL,
        "keywords": [
            "practice",
            "free practice",
            "fp1",
            "fp2",
            "fp3",
            "qualifying",
            "sprint",
            "race",
            "grand prix"
        ]
    },
    {
        "series": "motogp",
        "source": MOTOGP_ICS_URL,
        "keywords": [
            "practice",
            "pr1",
            "pr2",
            "p1",
            "p2",
            "qualifying",
            "qualifying 1",
            "qualifying 2",
            "q1",
            "q2",
            "sprint",
            "warm up",
            "warmup",
            "race",
            "grand prix",
            "gara",
            "qualifiche",
            "prove libere"
        ]
    }
]


def load_sent_events():
    if not os.path.exists(SENT_FILE):
        return {}

    try:
        with open(SENT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_sent_events(data):
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }

    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()


def load_calendar_source(source):
    if source.startswith("http://") or source.startswith("https://"):
        print(f"scarico calendario remoto: {source}")
        response = requests.get(source, timeout=20)
        response.raise_for_status()
        return response.content

    print(f"apro calendario locale: {source}")
    with open(source, "rb") as f:
        return f.read()


def parse_events(ics_content):
    cal = Calendar.from_ical(ics_content)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        summary = str(component.get("summary", "Evento Motorsport"))
        dtstart = component.get("dtstart").dt

        if hasattr(dtstart, "tzinfo") and dtstart.tzinfo is not None:
            event_time = dtstart
        else:
            event_time = parser.parse(str(dtstart))

        events.append({
            "summary": summary,
            "start": event_time
        })

    return events


def normalize_datetime(dt, timezone_name):
    tz = pytz.timezone(timezone_name)

    if dt.tzinfo is None:
        return tz.localize(dt)

    return dt.astimezone(tz)


def should_notify(event_time, now, remind_before_minutes):
    target_time = event_time - timedelta(minutes=remind_before_minutes)
    delta_seconds = (now - target_time).total_seconds()
    return 0 <= delta_seconds < 360


def make_event_id(series_name, summary, start_dt):
    return f"{series_name}_{summary}_{start_dt.isoformat()}"


def is_allowed_session(summary, keywords):
    lower = summary.lower()
    return any(keyword in lower for keyword in keywords)


def prettify_summary(summary):
    text = summary.replace("_", " ").strip()

    replacements = {
        "motogp": "MotoGP",
        "formula 1": "Formula 1",
        "f1": "F1",
        "fp1": "FP1",
        "fp2": "FP2",
        "fp3": "FP3",
        "pr1": "PR1",
        "pr2": "PR2",
        "p1": "P1",
        "p2": "P2",
        "q1": "Q1",
        "q2": "Q2",
        "grand prix": "Grand Prix",
        "qualifying": "Qualifying",
        "qualifiche": "Qualifiche",
        "sprint": "Sprint",
        "warm up": "Warm Up",
        "warmup": "Warm Up",
        "race": "Race",
        "gara": "Gara",
        "practice": "Practice",
        "prove libere": "Prove Libere"
    }

    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
        result = result.replace(old.capitalize(), new)
        result = result.replace(old.upper(), new)

    return result


def format_message(series_name, summary, start_local):
    clean_summary = escape(prettify_summary(summary))
    date_str = start_local.strftime("%d/%m/%Y")
    time_str = start_local.strftime("%H:%M")

    if series_name == "f1":
        icon = "🏎️"
        title = "F1 Alert"
        category = "Formula 1"
    elif series_name == "motogp":
        icon = "🏍️"
        title = "MotoGP Alert"
        category = "MotoGP"
    else:
        icon = "🏁"
        title = "Motorsport Alert"
        category = "Motorsport"

    return (
        f"{icon} <b>{title}</b>\n\n"
        f"<b>Campionato:</b> {category}\n"
        f"<b>Sessione:</b> {clean_summary}\n"
        f"<b>Data:</b> {date_str}\n"
        f"<b>Ora:</b> {time_str}\n"
        f"<b>Fuso orario:</b> {TIMEZONE}\n\n"
        f"<b>Promemoria:</b> {REMIND_BEFORE_MINUTES} minuti prima\n\n"
        f"<i>Preparati, la sessione sta per cominciare.</i>"
    )


def main():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    print(f"ora attuale: {now.isoformat()}")

    sent_events = load_sent_events()

    for calendar_info in CALENDARS:
        series = calendar_info["series"]
        source = calendar_info["source"]
        keywords = calendar_info["keywords"]

        print(f"\n--- controllo calendario {series} ---")

        try:
            ics_content = load_calendar_source(source)
            events = parse_events(ics_content)
        except Exception as e:
            print(f"errore nel caricamento calendario {series}: {e}")
            continue

        print(f"eventi trovati per {series}: {len(events)}")

        for event in events:
            summary = event["summary"]
            start_local = normalize_datetime(event["start"], TIMEZONE)

            if start_local < now:
                continue

            if not is_allowed_session(summary, keywords):
                continue

            event_id = make_event_id(series, summary, start_local)

            if event_id in sent_events:
                continue

            if should_notify(start_local, now, REMIND_BEFORE_MINUTES):
                text = format_message(series, summary, start_local)

                try:
                    send_telegram_message(text)
                    print(f"notifica inviata per {series}: {summary}")

                    sent_events[event_id] = {
                        "series": series,
                        "summary": summary,
                        "start": start_local.isoformat(),
                        "sent_at": now.isoformat()
                    }
                except Exception as e:
                    print(f"errore invio telegram per {series}: {e}")

    save_sent_events(sent_events)


if __name__ == "__main__":
    main()
