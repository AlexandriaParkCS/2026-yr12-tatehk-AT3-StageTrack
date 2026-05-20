from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from ..auth.routes import current_user, login_required, role_required
from ..email_service import send_task_assignment_email, send_task_update_email
from ..extensions import db
from ..models import Event, Task, User
from . import tasks_bp


DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
STATUS_OPTIONS = ["Pending", "In Progress", "Completed"]
MANAGER_ROLES = {"Admin", "Teacher", "Stage Manager"}
DEFAULT_TASK_ROWS = 1
MAX_TASK_ROWS = 25


def parse_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, DATETIME_FORMAT)


def is_manager(user):
    return user and user.role in MANAGER_ROLES


def task_state(task, now=None):
    current_time = now or datetime.now()
    if task.status == "Completed":
        return "Completed"
    if task.due_time and task.due_time < current_time:
        return "Overdue"
    if task.due_time:
        return "Due Soon" if (task.due_time - current_time).total_seconds() <= 24 * 3600 else task.status
    return task.status


def load_task_form_choices():
    events = Event.query.order_by(Event.event_date.asc()).all()
    users = User.query.order_by(User.name.asc()).all()
    return events, users


def submitted_bulk_rows():
    rows = []
    row_count = request.form.get("task_entry_count", type=int) or DEFAULT_TASK_ROWS
    row_count = max(DEFAULT_TASK_ROWS, min(row_count, MAX_TASK_ROWS))
    for index in range(row_count):
        title = request.form.get(f"title_{index}", "").strip()
        assigned_to = request.form.get(f"assigned_to_{index}", type=int)
        due_time_raw = request.form.get(f"due_time_{index}", "").strip()
        description = request.form.get(f"description_{index}", "").strip()
        status = request.form.get(f"status_{index}", "Pending").strip() or "Pending"
        due_time = parse_datetime(due_time_raw) if due_time_raw else None
        if title or assigned_to or description or due_time_raw:
            rows.append(
                {
                    "title": title,
                    "assigned_to": assigned_to,
                    "due_time": due_time,
                    "description": description,
                    "status": status,
                }
            )
    return rows


@tasks_bp.route("/")
@login_required
def index():
    user = current_user()
    selected_status = request.args.get("status", "").strip()
    selected_event_id = request.args.get("event_id", type=int)
    selected_assignee_id = request.args.get("assigned_to", type=int)
    search = request.args.get("q", "").strip().lower()
    query = Task.query

    if not is_manager(user):
        query = query.filter_by(assigned_to=user.id)

    if selected_status in STATUS_OPTIONS:
        query = query.filter_by(status=selected_status)
    if selected_event_id:
        query = query.filter_by(event_id=selected_event_id)
    if selected_assignee_id and is_manager(user):
        query = query.filter_by(assigned_to=selected_assignee_id)

    tasks = query.order_by(Task.due_time.asc(), Task.created_at.desc()).all()
    if search:
        tasks = [
            task for task in tasks
            if search in " ".join([task.title, task.description or "", task.event.name, task.assignee.name]).lower()
        ]
    return render_template(
        "tasks/index.html",
        tasks=tasks,
        statuses=STATUS_OPTIONS,
        current_status=selected_status,
        is_manager=is_manager(user),
        current_event_id=selected_event_id,
        current_assignee_id=selected_assignee_id,
        current_search=search,
        events=Event.query.order_by(Event.event_date.asc()).all(),
        users=User.query.order_by(User.name.asc()).all(),
        now=datetime.now(),
        task_state=task_state,
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
            try:
                send_task_assignment_email(task)
            except Exception:
                pass
            flash("Task created.", "success")
            return redirect(url_for("tasks.index"))

    return render_template("tasks/form.html", task=None, events=events, users=users, statuses=STATUS_OPTIONS)


@tasks_bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(task_id):
    task = Task.query.get_or_404(task_id)
    events, users = load_task_form_choices()

    if request.method == "POST":
        original_assigned_to = task.assigned_to
        original_status = task.status
        original_due_time = task.due_time
        original_title = task.title
        original_description = task.description
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
            if (
                task.assigned_to != original_assigned_to
                or task.status != original_status
                or task.due_time != original_due_time
                or task.title != original_title
                or task.description != original_description
            ):
                try:
                    send_task_update_email(task)
                except Exception:
                    pass
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
    try:
        send_task_update_email(task)
    except Exception:
        pass
    flash("Task status updated.", "success")
    next_url = request.form.get("next", "").strip()
    return redirect(next_url or url_for("tasks.index"))


@tasks_bp.route("/bulk", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def bulk_create():
    event_id = request.form.get("event_id", type=int)
    event = db.session.get(Event, event_id) if event_id else None
    next_url = request.form.get("next", "").strip() or (url_for("events.detail", event_id=event.id) if event else url_for("tasks.index"))
    if not event:
        flash("Select a valid event before adding tasks.", "error")
        return redirect(next_url)

    try:
        rows = submitted_bulk_rows()
    except ValueError:
        flash("Please enter valid due times for each task row.", "error")
        return redirect(next_url)

    if not rows:
        flash("Add at least one task row before saving.", "error")
        return redirect(next_url)

    created_tasks = []
    for row in rows:
        assignee = db.session.get(User, row["assigned_to"]) if row["assigned_to"] else None
        if not row["title"] or row["status"] not in STATUS_OPTIONS or not assignee:
            flash("Each task row needs a title, assignee, and valid status.", "error")
            return redirect(next_url)
        task = Task(
            event_id=event.id,
            assigned_to=assignee.id,
            title=row["title"],
            description=row["description"],
            status=row["status"],
            due_time=row["due_time"],
        )
        db.session.add(task)
        created_tasks.append(task)

    db.session.commit()
    for task in created_tasks:
        try:
            send_task_assignment_email(task)
        except Exception:
            pass

    flash(f"{len(created_tasks)} task{'s' if len(created_tasks) != 1 else ''} added to {event.name}.", "success")
    return redirect(next_url)


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def delete(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("tasks.index"))
