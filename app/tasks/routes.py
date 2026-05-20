from datetime import datetime, timedelta

from flask import flash, jsonify, redirect, render_template, request, url_for

from ..auth.routes import current_user, login_required, role_required
from ..email_service import send_task_assignment_email, send_task_update_email
from ..extensions import db
from ..models import Event, EventCrewAssignment, Task, TaskComment, TaskTemplate, TaskTemplateItem, User
from ..system_settings_service import event_crew_roles, get_system_settings
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
    users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    return events, users


def load_template_choices():
    return TaskTemplate.query.order_by(TaskTemplate.name.asc()).all()


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


def submitted_template_rows():
    rows = []
    row_count = request.form.get("template_entry_count", type=int) or DEFAULT_TASK_ROWS
    row_count = max(DEFAULT_TASK_ROWS, min(row_count, MAX_TASK_ROWS))
    for index in range(row_count):
        title = request.form.get(f"template_title_{index}", "").strip()
        role_hint = request.form.get(f"template_role_{index}", "").strip()
        due_offset = request.form.get(f"template_due_offset_{index}", type=int)
        description = request.form.get(f"template_description_{index}", "").strip()
        if title or role_hint or description or due_offset is not None:
            rows.append(
                {
                    "title": title,
                    "role_hint": role_hint,
                    "due_offset_minutes": due_offset,
                    "description": description,
                }
            )
    return rows


def task_comment_payload():
    return (request.form.get("comment", "") or request.form.get("note", "") or "").strip()


def task_status_json(task):
    now = datetime.now()
    return {
        "ok": True,
        "task_id": task.id,
        "status": task.status,
        "display_status": task_state(task, now),
        "due_label": task.due_time.strftime("%d %b %Y %I:%M %p") if task.due_time else "Not set",
    }


def apply_template_to_event(template, event):
    notifications = []
    created_count = 0
    role_matches = {assignment.crew_role.lower(): assignment.user_id for assignment in event.crew_assignments if assignment.user_id}

    for item in template.items:
        assignee_id = role_matches.get((item.role_hint or "").strip().lower())
        if not assignee_id:
            fallback_assignment = event.crew_assignments[0].user_id if event.crew_assignments else current_user().id
            assignee_id = fallback_assignment
        due_time = None
        if item.due_offset_minutes is not None:
            base_time = event.setup_time or event.event_date
            due_time = base_time + timedelta(minutes=item.due_offset_minutes)
        task = Task(
            event_id=event.id,
            assigned_to=assignee_id,
            title=item.title,
            description=item.description,
            due_time=due_time,
            status="Pending",
        )
        db.session.add(task)
        db.session.flush()
        notifications.append(task)
        created_count += 1

    db.session.commit()
    for task in notifications:
        try:
            send_task_assignment_email(task)
        except Exception:
            pass
    return created_count


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
        templates=load_template_choices(),
    )


@tasks_bp.route("/today")
@login_required
def today():
    user = current_user()
    now = datetime.now()
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)
    tasks = (
        Task.query.filter_by(assigned_to=user.id)
        .filter(Task.status != "Completed")
        .filter(Task.due_time.is_not(None))
        .filter(Task.due_time <= end_of_day)
        .order_by(Task.due_time.asc(), Task.created_at.asc())
        .all()
    )
    events = (
        EventCrewAssignment.query.join(Event)
        .filter(EventCrewAssignment.user_id == user.id, Event.event_date >= now)
        .order_by(Event.event_date.asc())
        .limit(3)
        .all()
    )
    equipment = user.checkouts
    active_equipment = [checkout for checkout in equipment if checkout.return_time is None][:5]
    return render_template("tasks/today.html", tasks=tasks, events=events, active_equipment=active_equipment, now=now, task_state=task_state)


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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "You do not have permission to update that task."}), 403
        return redirect(next_url or url_for("tasks.index"))

    if new_status not in STATUS_OPTIONS:
        flash("Invalid task status.", "error")
        next_url = request.form.get("next", "").strip()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": "Invalid task status."}), 400
        return redirect(next_url or url_for("tasks.index"))

    task.status = new_status
    note = task_comment_payload()
    if note:
        db.session.add(TaskComment(task_id=task.id, user_id=user.id, body=note))
    db.session.commit()
    try:
        send_task_update_email(task)
    except Exception:
        pass
    flash("Task status updated.", "success")
    next_url = request.form.get("next", "").strip()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(task_status_json(task))
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


@tasks_bp.route("/<int:task_id>/comment", methods=["POST"])
@login_required
def add_comment(task_id):
    task = Task.query.get_or_404(task_id)
    user = current_user()
    if task.assigned_to != user.id and not is_manager(user):
        flash("You do not have permission to add notes to that task.", "error")
        return redirect(request.form.get("next", "").strip() or url_for("tasks.index"))

    body = request.form.get("body", "").strip()
    if not body:
        flash("Write a note before posting it.", "error")
        return redirect(request.form.get("next", "").strip() or url_for("tasks.index"))

    db.session.add(TaskComment(task_id=task.id, user_id=user.id, body=body))
    db.session.commit()
    flash("Task note added.", "success")
    return redirect(request.form.get("next", "").strip() or url_for("tasks.index"))


@tasks_bp.route("/templates")
@role_required("Admin", "Teacher", "Stage Manager")
def templates():
    return render_template("tasks/templates/index.html", templates=load_template_choices())


@tasks_bp.route("/templates/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create_template():
    if request.method == "POST":
        rows = submitted_template_rows()
        template = TaskTemplate(
            name=request.form.get("name", "").strip(),
            description=request.form.get("description", "").strip() or None,
        )
        if not template.name or not rows:
            flash("Template name and at least one task row are required.", "error")
            return render_template("tasks/templates/form.html", template=None, rows=rows or [{}], role_hints=event_crew_roles())
        db.session.add(template)
        db.session.flush()
        for row in rows:
            if not row["title"]:
                continue
            template.items.append(
                TaskTemplateItem(
                    title=row["title"],
                    description=row["description"] or None,
                    role_hint=row["role_hint"] or None,
                    due_offset_minutes=row["due_offset_minutes"],
                )
            )
        db.session.commit()
        flash("Task template created.", "success")
        return redirect(url_for("tasks.templates"))
    return render_template("tasks/templates/form.html", template=None, rows=[{}], role_hints=event_crew_roles())


@tasks_bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit_template(template_id):
    template = TaskTemplate.query.get_or_404(template_id)
    if request.method == "POST":
        rows = submitted_template_rows()
        template.name = request.form.get("name", "").strip()
        template.description = request.form.get("description", "").strip() or None
        if not template.name or not rows:
            flash("Template name and at least one task row are required.", "error")
            return render_template("tasks/templates/form.html", template=template, rows=rows or [{}], role_hints=event_crew_roles())
        template.items.clear()
        for row in rows:
            if not row["title"]:
                continue
            template.items.append(
                TaskTemplateItem(
                    title=row["title"],
                    description=row["description"] or None,
                    role_hint=row["role_hint"] or None,
                    due_offset_minutes=row["due_offset_minutes"],
                )
            )
        db.session.commit()
        flash("Task template updated.", "success")
        return redirect(url_for("tasks.templates"))
    rows = [
        {
            "title": item.title,
            "description": item.description or "",
            "role_hint": item.role_hint or "",
            "due_offset_minutes": item.due_offset_minutes if item.due_offset_minutes is not None else "",
        }
        for item in template.items
    ] or [{}]
    return render_template("tasks/templates/form.html", template=template, rows=rows, role_hints=event_crew_roles())


@tasks_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def delete_template(template_id):
    template = TaskTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    flash("Task template deleted.", "success")
    return redirect(url_for("tasks.templates"))


@tasks_bp.route("/templates/<int:template_id>/apply", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def apply_template(template_id):
    template = TaskTemplate.query.get_or_404(template_id)
    event_id = request.form.get("event_id", type=int)
    event = Event.query.get_or_404(event_id)
    created_count = apply_template_to_event(template, event)
    flash(f"{template.name} applied to {event.name}. {created_count} tasks created.", "success")
    return redirect(request.form.get("next", "").strip() or url_for("events.detail", event_id=event.id))


@tasks_bp.route("/templates/save-from-event/<int:event_id>", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def save_template_from_event(event_id):
    event = Event.query.get_or_404(event_id)
    name = request.form.get("name", "").strip() or f"{event.name} template"
    if not event.tasks:
        flash("This event has no tasks to save as a template yet.", "error")
        return redirect(url_for("events.detail", event_id=event.id))
    template = TaskTemplate(name=name, description=event.description or None, source_event_id=event.id)
    db.session.add(template)
    db.session.flush()
    role_map = {assignment.user_id: assignment.crew_role for assignment in event.crew_assignments}
    base_time = event.setup_time or event.event_date
    for task in event.tasks:
        offset = None
        if task.due_time and base_time:
            offset = int((task.due_time - base_time).total_seconds() // 60)
        template.items.append(
            TaskTemplateItem(
                title=task.title,
                description=task.description or None,
                role_hint=role_map.get(task.assigned_to),
                due_offset_minutes=offset,
            )
        )
    db.session.commit()
    flash("Event tasks saved as a reusable template.", "success")
    return redirect(url_for("events.detail", event_id=event.id))


@tasks_bp.route("/<int:task_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def delete(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("tasks.index"))
