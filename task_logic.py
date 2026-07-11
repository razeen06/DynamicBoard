from datetime import datetime, timedelta
from constants import DAYS, DEFAULT_START_HOUR, DEFAULT_END_HOUR
from data_store import save_current_user_data


def calculate_days_until_due(due_date):
    try:
        today = datetime.today().date()
        due = datetime.strptime(due_date, "%Y-%m-%d").date()
        days_left = (due - today).days
        return max(days_left, 0)
    except ValueError:
        return 999


def calculate_priority(importance, difficulty, hours_left, progress, due_date):
    importance = int(importance)
    difficulty = int(difficulty)
    hours_left = float(hours_left)
    progress = int(float(progress))

    days_left = calculate_days_until_due(due_date)

    urgency_score = 20 / (days_left + 1)
    importance_score = importance * 2
    difficulty_score = difficulty * 1.5
    effort_score = hours_left
    progress_penalty = (100 - progress) / 20

    priority = urgency_score + importance_score + difficulty_score + effort_score + progress_penalty
    return round(priority, 2)


def calculate_risk(priority):
    if priority >= 30:
        return "Critical"
    elif priority >= 20:
        return "High"
    elif priority >= 12:
        return "Medium"
    else:
        return "Low"


def refresh_task_scores(tasks):
    for task in tasks:
        task.setdefault("notes", "")
        task.setdefault("plan", "")

        if task.get("completed", False):
            task["priority"] = 0
            task["risk"] = "Done"
            task["days_left"] = 0
            task["progress"] = "100"
        else:
            priority = calculate_priority(
                task.get("importance", 1),
                task.get("difficulty", 1),
                task.get("estimated_hours", 0),
                task.get("progress", 0),
                task.get("due_date", "9999-12-31")
            )

            task["priority"] = priority
            task["risk"] = calculate_risk(priority)
            task["days_left"] = calculate_days_until_due(task.get("due_date", "9999-12-31"))

    return tasks


def get_sorted_tasks(user_data):
    tasks = refresh_task_scores(user_data["tasks"])

    tasks = sorted(
        tasks,
        key=lambda task: (task.get("completed", False), -task.get("priority", 0))
    )

    user_data["tasks"] = tasks
    save_current_user_data(user_data)

    return tasks


def time_to_minutes(time_string):
    try:
        hour, minute = time_string.split(":")
        return int(hour) * 60 + int(minute)
    except (ValueError, AttributeError):
        return DEFAULT_START_HOUR * 60


def time_to_hour(time_string):
    try:
        return int(time_string.split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return DEFAULT_START_HOUR


def get_week_days(week_offset=0):
    today = datetime.today().date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)

    week_days = []

    for index, day_name in enumerate(DAYS):
        day_date = week_start + timedelta(days=index)

        week_days.append({
            "name": day_name,
            "date": day_date.strftime("%Y-%m-%d"),
            "label": day_date.strftime("%d %b"),
            "is_today": day_date == today
        })

    week_end = week_start + timedelta(days=6)
    week_range_label = f"{week_start.strftime('%d %b')} – {week_end.strftime('%d %b %Y')}"

    return week_days, week_range_label, week_offset == 0


def get_timetable_hours(timetable, week_days):
    min_hour = DEFAULT_START_HOUR
    max_hour = DEFAULT_END_HOUR

    for day in week_days:
        for entry in timetable.get(day["date"], []):
            start_hour = time_to_hour(entry.get("start_time", "07:00"))
            end_hour = time_to_hour(entry.get("end_time", "20:00"))

            min_hour = min(min_hour, start_hour)
            max_hour = max(max_hour, end_hour)

    return [f"{hour:02d}:00" for hour in range(min_hour, max_hour + 1)]


def build_schedule_entries(timetable, timetable_hours, week_days):
    hour_to_row = {
        hour: index + 2
        for index, hour in enumerate(timetable_hours)
    }

    positioned_entries = []

    for day_index, day in enumerate(week_days):
        for entry in timetable.get(day["date"], []):
            start_time = entry.get("start_time", "07:00")
            end_time = entry.get("end_time", start_time)

            start_hour = time_to_hour(start_time)
            end_hour = time_to_hour(end_time)

            start_key = f"{start_hour:02d}:00"

            if start_key not in hour_to_row:
                continue

            row_start = hour_to_row[start_key]
            row_span = max(1, end_hour - start_hour)

            positioned_entries.append({
                **entry,
                "date": day["date"],
                "grid_column": day_index + 2,
                "grid_row": row_start,
                "grid_span": row_span
            })

    return positioned_entries


def get_today_timetable_entries(timetable):
    today_key = datetime.today().date().strftime("%Y-%m-%d")
    entries = timetable.get(today_key, [])

    return sorted(entries, key=lambda entry: entry.get("start_time", "99:99"))