from flask import Blueprint, render_template, request, redirect, session, url_for, current_app
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
from uuid import uuid4
import random

from constants import PRODUCTIVITY_QUOTES, DAYS, DEFAULT_START_HOUR, DEFAULT_END_HOUR
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
    get_today_timetable_entries
)

oauth = OAuth()
main_routes = Blueprint("main_routes", __name__)


def render_dashboard(
    selected_task=None,
    selected_task_index=None,
    show_timetable=False,
    add_schedule_day=None,
    add_schedule_hour=None
):
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
            add_schedule_day=None,
            add_schedule_hour=None,
            timetable=default_timetable(),
            timetable_hours=default_hours,
            schedule_entries=[],
            days=DAYS,
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

    timetable_hours = get_timetable_hours(timetable)
    schedule_entries = build_schedule_entries(timetable, timetable_hours)

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
        add_schedule_day=add_schedule_day,
        add_schedule_hour=add_schedule_hour,
        timetable=timetable,
        timetable_hours=timetable_hours,
        schedule_entries=schedule_entries,
        days=DAYS,
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        critical_tasks=critical_tasks,
        total_hours_remaining=round(total_hours_remaining, 1),
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

    return render_dashboard(show_timetable=True)


@main_routes.route("/timetable/add/<day>/<hour>")
def add_timetable_entry(day, hour):
    if not get_current_user_key():
        return redirect("/")

    if day not in DAYS:
        return redirect("/timetable")

    return render_dashboard(
        show_timetable=True,
        add_schedule_day=day,
        add_schedule_hour=hour
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

    day = request.form.get("day")
    linked_task_index = request.form.get("linked_task_index")
    custom_title = request.form.get("custom_title", "").strip()
    details = request.form.get("details", "").strip()
    start_time = request.form.get("start_time")
    end_time = request.form.get("end_time")

    if day not in DAYS:
        return redirect("/timetable")

    if not start_time or not end_time:
        return redirect("/timetable")

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

    user_data["timetable"] = normalize_timetable(user_data.get("timetable", default_timetable()))
    user_data["timetable"][day].append(entry)

    user_data["timetable"][day] = sorted(
        user_data["timetable"][day],
        key=lambda item: item.get("start_time", "99:99")
    )

    save_current_user_data(user_data)

    return redirect("/timetable")


@main_routes.route("/delete_schedule_entry/<entry_id>", methods=["POST"])
def delete_schedule_entry(entry_id):
    user_data = get_current_user_data()

    if not user_data:
        return redirect("/")

    timetable = normalize_timetable(user_data.get("timetable", default_timetable()))

    for day in DAYS:
        timetable[day] = [
            entry for entry in timetable[day]
            if entry.get("id") != entry_id
        ]

    user_data["timetable"] = timetable
    save_current_user_data(user_data)

    return redirect("/timetable")


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