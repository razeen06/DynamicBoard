from flask import Blueprint, render_template, request, redirect, session, url_for, current_app
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
from uuid import uuid4
import random

from constants import PRODUCTIVITY_QUOTES, DEFAULT_START_HOUR, DEFAULT_END_HOUR
from data_store import (
    default_timetable,
    default_user_data,
    load_data,
    save_data,
    get_current_user_key,
    get_current_display_name,
    get_current_user_data,
    save_current_user_data,
    normalize_timetable
)
from task_logic import (
    calculate_days_until_due,
    calculate_priority,
    calculate_risk,
    refresh_task_scores,
    get_sorted_tasks,
    time_to_minutes,
    get_timetable_hours,
    build_schedule_entries,
    get_today_timetable_entries,
    get_week_days
)

oauth = OAuth()
main_routes = Blueprint("main_routes", __name__)


def parse_week_offset(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def render_dashboard(
    selected_task=None,
    selected_task_index=None,
    show_timetable=False,
    add_schedule_date=None,
    add_schedule_label=None,
    add_schedule_hour=None,
    week_offset=0
):
    week_days, week_range_label, is_current_week = get_week_days(week_offset)
    user_key = get_current_user_key()

    if not user_key:
        default_hours = [
            f"{hour:02d}:00"
            for hour in range(DEFAULT_START_HOUR, DEFAULT_END_HOUR + 1)
        ]

        return render_template(
            "index.html",
            logged_in=False,
            user_email=None,
            user_name=None,
            board_title="DynamicBoard",
            quote=random.choice(PRODUCTIVITY_QUOTES),
            settings={"theme": "dark", "zoom": "medium"},
            tasks=[],
            todays_focus=[],
            today_timetable=[],
            selected_task=None,
            selected_task_index=None,
            show_timetable=False,
            add_schedule_date=None,
            add_schedule_label=None,
            add_schedule_hour=None,
            timetable=default_timetable(),
            timetable_hours=default_hours,
            schedule_entries=[],
            week_offset=0,
            week_days=[],
            week_range_label="",
            is_current_week=True,
            total_tasks=0,
            completed_tasks=0,
            critical_tasks=0,
            total_hours_remaining=0,
            oauth_ready=current_app.config.get("OAUTH_READY", False)
        )

    user_data = get_current_user_data()
    tasks = get_sorted_tasks(user_data)
    settings = user_data["settings"]
    timetable = user_data["timetable"]

    incomplete_tasks = [task for task in tasks if not task.get("completed", False)]

    todays_focus = [
        task for task in incomplete_tasks
        if task.get("risk") in ["Critical", "High"]
    ][:5]

    today_timetable = get_today_timetable_entries(timetable)

    total_tasks = len(tasks)
    completed_tasks = len([task for task in tasks if task.get("completed", False)])
    critical_tasks = len([task for task in incomplete_tasks if task.get("risk") == "Critical"])

    total_hours_remaining = sum(
        float(task.get("estimated_hours", 0))
        for task in incomplete_tasks
    )

    display_name = get_current_display_name()
    first_name = display_name.split()[0] if display_name else "User"

    timetable_hours = get_timetable_hours(timetable, week_days)
    schedule_entries = build_schedule_entries(timetable, timetable_hours, week_days)

    return render_template(
        "index.html",
        logged_in=True,
        user_email=user_key,
        user_name=display_name,
        board_title=f"{first_name}'s board",
        quote=random.choice(PRODUCTIVITY_QUOTES),
        settings=settings,
        tasks=tasks,
        todays_focus=todays_focus,
        today_timetable=today_timetable,
        selected_task=selected_task,
        selected_task_index=selected_task_index,
        show_timetable=show_timetable,
        add_schedule_date=add_schedule_date,
        add_schedule_label=add_schedule_label,
        add_schedule_hour=add_schedule_hour,
        timetable=timetable,
        timetable_hours=timetable_hours,
        schedule_entries=schedule_entries,
        week_offset=week_offset,
        week_days=week_days,
        week_range_label=week_range_label,
        is_current_week=is_current_week,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        critical_tasks=critical_tasks,
        total_hours_remaining=round(total_hours_remaining, 1),
        today_day=datetime.today().strftime("%A"),
        today_date=datetime.today().strftime("%d %B %Y"),
        oauth_ready=current_app.config.get("OAUTH_READY", False)
    )


@main_routes.route("/")
def home():
    return render_dashboard()


@main_routes.route("/login")
def login():
    if not current_app.config.get("OAUTH_READY", False):
        return "Google OAuth is not configured. Check your .env file.", 500

    redirect_uri = url_for("main_routes.auth_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@main_routes.route("/auth/google/callback")
def auth_google_callback():
    token = oauth.google.authorize_access_token()

    user_info = token.get("userinfo")

    if not user_info:
        user_info = oauth.google.userinfo()

    user_email = user_info.get("email")
    user_name = user_info.get("name", user_email)

    if not user_email:
        return "Google login failed: no email returned.", 400

    session["user_email"] = user_email
    session["user_name"] = user_name

    data = load_data()

    if user_email not in data["users"]:
        data["users"][user_email] = default_user_data()
        save_data(data)

    return redirect("/")


@main_routes.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


@main_routes.route("/task/<int:task_index>")
def view_task(task_index):
    if not get_current_user_key():
        return redirect("/")

    user_data = get_current_user_data()
    tasks = get_sorted_tasks(user_data)

    selected_task = None

    if 0 <= task_index < len(tasks):
        selected_task = tasks[task_index]

    return render_dashboard(
        selected_task=selected_task,
        selected_task_index=task_index
    )


@main_routes.route("/timetable")
def view_timetable():
    if not get_current_user_key():
        return redirect("/")

    week_offset = parse_week_offset(request.args.get("week_offset"))

    return render_dashboard(show_timetable=True, week_offset=week_offset)


@main_routes.route("/timetable/add/<date>/<hour>")
def add_timetable_entry(date, hour):
    if not get_current_user_key():
        return redirect("/")

    week_offset = parse_week_offset(request.args.get("week_offset"))

    try:
        add_schedule_label = datetime.strptime(date, "%Y-%m-%d").strftime("%A, %d %b %Y")
    except ValueError:
        return redirect(f"/timetable?week_offset={week_offset}")

    return render_dashboard(
        show_timetable=True,
        add_schedule_date=date,
        add_schedule_label=add_schedule_label,
        add_schedule_hour=hour,
        week_offset=week_offset
    )


@main_routes.route("/settings", methods=["POST"])
def update_settings():
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    theme = request.form.get("theme", user_data["settings"].get("theme", "dark"))
    zoom = request.form.get("zoom", user_data["settings"].get("zoom", "medium"))

    user_data["settings"] = {
        "theme": theme,
        "zoom": zoom
    }

    save_current_user_data(user_data)
    return redirect("/")


@main_routes.route("/add", methods=["POST"])
def add_task():
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    tasks = user_data["tasks"]

    title = request.form.get("title")
    importance = request.form.get("importance")
    difficulty = request.form.get("difficulty")
    due_days = request.form.get("due_days")
    hours_left = request.form.get("estimated_hours")
    progress = request.form.get("progress")

    if title and due_days:
        due_date = (datetime.today().date() + timedelta(days=int(due_days))).strftime("%Y-%m-%d")

        priority = calculate_priority(
            importance,
            difficulty,
            hours_left,
            progress,
            due_date
        )

        risk = calculate_risk(priority)
        days_left = calculate_days_until_due(due_date)

        tasks.append({
            "title": title,
            "importance": importance,
            "difficulty": difficulty,
            "due_date": due_date,
            "estimated_hours": hours_left,
            "progress": progress,
            "priority": priority,
            "risk": risk,
            "days_left": days_left,
            "notes": "",
            "plan": "",
            "completed": False
        })

        user_data["tasks"] = tasks
        save_current_user_data(user_data)

    return redirect("/")


@main_routes.route("/update_progress/<int:task_index>", methods=["POST"])
def update_progress(task_index):
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    tasks = get_sorted_tasks(user_data)

    if 0 <= task_index < len(tasks):
        new_progress = request.form.get("progress")
        new_hours_left = request.form.get("estimated_hours")

        tasks[task_index]["progress"] = new_progress
        tasks[task_index]["estimated_hours"] = new_hours_left

        if int(new_progress) >= 100:
            tasks[task_index]["completed"] = True

        tasks = refresh_task_scores(tasks)
        user_data["tasks"] = tasks
        save_current_user_data(user_data)

    return redirect(f"/task/{task_index}")


@main_routes.route("/update_notes/<int:task_index>", methods=["POST"])
def update_notes(task_index):
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    tasks = get_sorted_tasks(user_data)

    if 0 <= task_index < len(tasks):
        tasks[task_index]["notes"] = request.form.get("notes", "")
        tasks[task_index]["plan"] = request.form.get("plan", "")

        user_data["tasks"] = tasks
        save_current_user_data(user_data)

    return redirect(f"/task/{task_index}")


@main_routes.route("/save_schedule_entry", methods=["POST"])
def save_schedule_entry():
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    date = request.form.get("date")
    linked_task_index = request.form.get("linked_task_index")
    custom_title = request.form.get("custom_title", "").strip()
    details = request.form.get("details", "").strip()
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")
    week_offset = parse_week_offset(request.form.get("week_offset"))

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return redirect(f"/timetable?week_offset={week_offset}")

    if not start_time or not end_time:
        return redirect(f"/timetable?week_offset={week_offset}")

    if time_to_minutes(end_time) < time_to_minutes(start_time):
        start_minutes = time_to_minutes(start_time)
        corrected_end_hour = min(23, start_minutes // 60 + 1)
        end_time = f"{corrected_end_hour:02d}:00"

    tasks = get_sorted_tasks(user_data)

    linked_task_title = ""
    title = custom_title

    if linked_task_index not in [None, ""]:
        task_index = int(linked_task_index)

        if 0 <= task_index < len(tasks):
            linked_task_title = tasks[task_index].get("title", "")
            title = linked_task_title

    if not title:
        title = "Untitled session"

    entry = {
        "id": str(uuid4()),
        "title": title,
        "details": details,
        "start_time": start_time,
        "end_time": end_time,
        "linked_task_title": linked_task_title
    }

    timetable = normalize_timetable(user_data.get("timetable", default_timetable()))
    timetable.setdefault(date, []).append(entry)

    timetable[date] = sorted(
        timetable[date],
        key=lambda item: item.get("start_time", "99:99")
    )

    user_data["timetable"] = timetable
    save_current_user_data(user_data)

    return redirect(f"/timetable?week_offset={week_offset}")


@main_routes.route("/delete_schedule_entry/<entry_id>", methods=["POST"])
def delete_schedule_entry(entry_id):
    user_data = get_current_user_data()
    week_offset = parse_week_offset(request.form.get("week_offset"))

    if not user_data:
        return redirect("/")

    timetable = normalize_timetable(user_data.get("timetable", default_timetable()))

    for date_key in timetable:
        timetable[date_key] = [
            entry for entry in timetable[date_key]
            if entry.get("id") != entry_id
        ]

    user_data["timetable"] = timetable
    save_current_user_data(user_data)

    return redirect(f"/timetable?week_offset={week_offset}")


@main_routes.route("/complete/<int:task_index>", methods=["POST"])
def complete_task(task_index):
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    tasks = get_sorted_tasks(user_data)

    if 0 <= task_index < len(tasks):
        tasks[task_index]["completed"] = True
        tasks[task_index]["progress"] = "100"
        tasks[task_index]["priority"] = 0
        tasks[task_index]["risk"] = "Done"

    user_data["tasks"] = tasks
    save_current_user_data(user_data)

    return redirect("/")


@main_routes.route("/delete/<int:task_index>", methods=["POST"])
def delete_task(task_index):
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    tasks = get_sorted_tasks(user_data)

    if 0 <= task_index < len(tasks):
        tasks.pop(task_index)

    user_data["tasks"] = tasks
    save_current_user_data(user_data)

    return redirect("/")