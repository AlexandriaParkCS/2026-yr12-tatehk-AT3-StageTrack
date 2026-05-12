from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from ..auth.routes import current_user, login_required, role_required
from ..extensions import db
from ..models import Event, Task, User
from . import tasks_bp


DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
STATUS_OPTIONS = ["Pending", "In Progress", "Completed"]
MANAGER_ROLES = {"Admin", "Teacher", "Stage Manager"}


def parse_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, DATETIME_FORMAT)


def is_manager(user):
    return user and user.role in MANAGER_ROLES


def load_task_form_choices():
    events = Event.query.order_by(Event.event_date.asc()).all()
    users = User.query.order_by(User.name.asc()).all()
    return events, users


@tasks_bp.route("/")
@login_required
def index():
    user = current_user()
    selected_status = request.args.get("status", "").strip()
    query = Task.query

    if not is_manager(user):
        query = query.filter_by(assigned_to=user.id)

    if selected_status in STATUS_OPTIONS:
        query = query.filter_by(status=selected_status)

    tasks = query.order_by(Task.due_time.asc(), Task.created_at.desc()).all()
    return render_template(
        "tasks/index.html",
        tasks=tasks,
        statuses=STATUS_OPTIONS,
        current_status=selected_status,
        is_manager=is_manager(user),
    )


@tasks_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    events, users = load_task_form_choices()
    if not events or not users:
        flash("Add at least one event and one user before creating tasks.", "error")
        return redirect(url_for("tasks.index"))

    if request.method == "POST":
        try:
            task = Task(
                event_id=int(request.form.get("event_id", "0")),
                assigned_to=int(request.form.get("assigned_to", "0")),
                title=request.form.get("title", "").strip(),
                description=request.form.get("description", "").strip(),
                status=request.form.get("status", "Pending").strip(),
                due_time=parse_datetime(request.form.get("due_time")),
            )
        except (TypeError, ValueError):
            flash("Please enter a valid due time.", "error")
            return render_template(
                "tasks/form.html",
                task=None,
                events=events,
                users=users,
                statuses=STATUS_OPTIONS,
            )

        event = db.session.get(Event, task.event_id)
        assignee = db.session.get(User, task.assigned_to)

        if not task.title or task.status not in STATUS_OPTIONS or not event or not assignee:
            flash("Please complete the required task fields.", "error")
        else:
            db.session.add(task)
            db.session.commit()
            flash("Task created.", "success")
            return redirect(url_for("tasks.index"))

    return render_template("tasks/form.html", task=None, events=events, users=users, statuses=STATUS_OPTIONS)


@tasks_bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(task_id):
    task = Task.query.get_or_404(task_id)
    events, users = load_task_form_choices()

    if request.method == "POST":
        try:
            task.event_id = int(request.form.get("event_id", "0"))
            task.assigned_to = int(request.form.get("assigned_to", "0"))
            task.title = request.form.get("title", "").strip()
            task.description = request.form.get("description", "").strip()
            task.status = request.form.get("status", "Pending").strip()
            task.due_time = parse_datetime(request.form.get("due_time"))
        except (TypeError, ValueError):
            flash("Please enter a valid due time.", "error")
            return render_template(
                "tasks/form.html",
                task=task,
                events=events,
                users=users,
                statuses=STATUS_OPTIONS,
            )

        event = db.session.get(Event, task.event_id)
        assignee = db.session.get(User, task.assigned_to)

        if not task.title or task.status not in STATUS_OPTIONS or not event or not assignee:
            flash("Please complete the required task fields.", "error")
        else:
            db.session.commit()
            flash("Task updated.", "success")
            return redirect(url_for("tasks.index"))

    return render_template("tasks/form.html", task=task, events=events, users=users, statuses=STATUS_OPTIONS)


@tasks_bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def update_status(task_id):
    task = Task.query.get_or_404(task_id)
    user = current_user()
    new_status = request.form.get("status", "").strip()

    if task.assigned_to != user.id and not is_manager(user):
        flash("You do not have permission to update that task.", "error")
        next_url = request.form.get("next", "").strip()
        return redirect(next_url or url_for("tasks.index"))

    if new_status not in STATUS_OPTIONS:
        flash("Invalid task status.", "error")
        next_url = request.form.get("next", "").strip()
        return redirect(next_url or url_for("tasks.index"))

    task.status = new_status
    db.session.commit()
    flash("Task status updated.", "success")
    next_url = request.form.get("next", "").strip()
    return redirect(next_url or url_for("tasks.index"))


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def delete(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("tasks.index"))
