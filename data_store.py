from flask import session
import json
import os
from uuid import uuid4

from constants import DATA_FILE, DAYS


def default_timetable():
    return {day: [] for day in DAYS}


def default_user_data():
    return {
        "settings": {
            "theme": "dark",
            "zoom": "medium"
        },
        "tasks": [],
        "timetable": default_timetable()
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}}

    try:
        with open(DATA_FILE, "r") as file:
            content = file.read().strip()

            if content == "":
                return {"users": {}}

            data = json.loads(content)

            if isinstance(data, list):
                return {
                    "users": {
                        "guest": {
                            "settings": {
                                "theme": "dark",
                                "zoom": "medium"
                            },
                            "tasks": data,
                            "timetable": default_timetable()
                        }
                    }
                }

            if "users" not in data:
                data["users"] = {}

            return data

    except json.JSONDecodeError:
        return {"users": {}}


def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)


def get_current_user_key():
    return session.get("user_email")


def get_current_display_name():
    return session.get("user_name", "User")


def normalize_timetable(timetable):
    if not isinstance(timetable, dict):
        return default_timetable()

    new_timetable = default_timetable()

    for day in DAYS:
        day_data = timetable.get(day, [])

        if isinstance(day_data, list):
            cleaned_entries = []

            for entry in day_data:
                if not isinstance(entry, dict):
                    continue

                cleaned_entries.append({
                    "id": entry.get("id", str(uuid4())),
                    "title": entry.get("title", "Untitled session"),
                    "details": entry.get("details", ""),
                    "start_time": entry.get("start_time", "09:00"),
                    "end_time": entry.get("end_time", "10:00"),
                    "linked_task_title": entry.get("linked_task_title", "")
                })

            new_timetable[day] = cleaned_entries

        elif isinstance(day_data, dict):
            converted = []

            rough_times = {
                "Morning": ("09:00", "11:00"),
                "Afternoon": ("13:00", "15:00"),
                "Evening": ("17:00", "19:00"),
                "Night": ("20:00", "22:00")
            }

            for block, text in day_data.items():
                if text:
                    start_time, end_time = rough_times.get(block, ("09:00", "10:00"))

                    converted.append({
                        "id": str(uuid4()),
                        "title": text,
                        "details": "",
                        "start_time": start_time,
                        "end_time": end_time,
                        "linked_task_title": ""
                    })

            new_timetable[day] = converted

    return new_timetable


def get_current_user_data():
    user_key = get_current_user_key()

    if not user_key:
        return None

    data = load_data()

    if user_key not in data["users"]:
        data["users"][user_key] = default_user_data()
        save_data(data)

    user_data = data["users"][user_key]

    if "settings" not in user_data:
        user_data["settings"] = {"theme": "dark", "zoom": "medium"}

    if "tasks" not in user_data:
        user_data["tasks"] = []

    if "timetable" not in user_data:
        user_data["timetable"] = default_timetable()

    user_data["timetable"] = normalize_timetable(user_data["timetable"])

    data["users"][user_key] = user_data
    save_data(data)

    return user_data


def save_current_user_data(user_data):
    user_key = get_current_user_key()

    if not user_key:
        return

    data = load_data()
    data["users"][user_key] = user_data
    save_data(data)