from datetime import datetime
from secrets import token_urlsafe

from flask import flash, redirect, render_template, request, send_file, url_for
from werkzeug.security import generate_password_hash

from ..auth.routes import current_user, login_required, role_required
from ..email_service import (
    build_event_invite_url,
    issue_password_reset_token,
    send_event_assignment_email,
    send_event_invite_email,
)
from ..extensions import db
from ..pdf_service import build_event_equipment_pdf
from ..models import Event, EventCrewAssignment, User
from ..system_settings_service import event_crew_roles, event_venues, get_system_settings, role_meets_requirement
from . import events_bp


DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
DEFAULT_CREW_ROWS = 1
MAX_CREW_ROWS = 30


def parse_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, DATETIME_FORMAT)


def blank_assignment_rows(count=DEFAULT_CREW_ROWS):
    return [{"email": "", "crew_role": ""} for _ in range(count)]


def existing_assignment_rows(event):
    rows = [
        {
            "email": assignment.crew_email or assignment.user.email,
            "crew_role": assignment.crew_role,
        }
        for assignment in event.crew_assignments
    ]
    return rows or blank_assignment_rows()


def submitted_assignment_rows():
    rows = []
    seen_emails = set()
    row_count = request.form.get("crew_entry_count", type=int) or DEFAULT_CREW_ROWS
    row_count = max(DEFAULT_CREW_ROWS, min(row_count, MAX_CREW_ROWS))

    for index in range(row_count):
        email = request.form.get(f"crew_email_{index}", "").strip().lower()
        crew_role = request.form.get(f"crew_role_{index}", "").strip()
        rows.append({"email": email, "crew_role": crew_role})

        if crew_role and not email:
            raise ValueError("Each crew role needs an email address.")
        if email and not crew_role:
            raise ValueError(f"Enter an event role for {email}.")
        if email:
            if email in seen_emails:
                raise ValueError(f"{email} has been entered more than once.")
            seen_emails.add(email)

    return rows or blank_assignment_rows()


def ensure_user_for_assignment(email):
    user = User.query.filter_by(email=email).first()
    created = False

    if not user:
        user = User(
            name="Pending crew member",
            email=email,
            password_hash=generate_password_hash(token_urlsafe(16)),
            must_change_password=True,
            role="Student Crew",
            is_active=True,
        )
        db.session.add(user)
        db.session.flush()
        created = True

    return user, created


def sync_event_assignments(event, assignment_rows):
    previous_assignments = {
        assignment.crew_email.lower(): assignment.crew_role
        for assignment in event.crew_assignments
    }

    event.crew_assignments.clear()
    notification_plan = []

    for row in assignment_rows:
        email = row["email"]
        crew_role = row["crew_role"]
        if not email:
            continue

        user, created = ensure_user_for_assignment(email)
        event.crew_assignments.append(
            EventCrewAssignment(
                user_id=user.id,
                crew_email=email,
                crew_role=crew_role,
            )
        )

        if previous_assignments.get(email) != crew_role:
            notification_plan.append({"user": user, "created": created, "crew_role": crew_role})

    return notification_plan


def send_assignment_notifications(event, notification_plan):
    if not get_system_settings().auto_send_event_invites:
        return []
    notices = []
    for item in notification_plan:
        user = item["user"]
        crew_role = item["crew_role"]
        try:
            if item["created"]:
                reset_token = issue_password_reset_token(user)
                invite_url = build_event_invite_url(reset_token)
                sent = send_event_invite_email(user, event, crew_role, invite_url)
                if not sent:
                    notices.append(f"Invite email for {user.email} could not be sent because email settings are incomplete.")
            else:
                sent = send_event_assignment_email(user, event, crew_role)
                if not sent:
                    notices.append(f"Assignment email for {user.email} could not be sent because email settings are incomplete.")
        except Exception as exc:
            notices.append(f"Email for {user.email} failed: {exc}")
    return notices


def current_user_can_view_event(event):
    user = current_user()
    if user.role in {"Admin", "Teacher", "Stage Manager", "Viewer"}:
        return True
    return any(assignment.user_id == user.id for assignment in event.crew_assignments)


@events_bp.route("/")
@login_required
def index():
    user = current_user()
    query = Event.query.order_by(Event.event_date.asc())

    if user.role == "Student Crew" and not get_system_settings().student_crew_can_view_all_events:
        query = query.join(EventCrewAssignment).filter(EventCrewAssignment.user_id == user.id)

    events = query.all()
    return render_template("events/index.html", events=events)


@events_bp.route("/<int:event_id>")
@login_required
def detail(event_id):
    event = Event.query.get_or_404(event_id)
    if not current_user_can_view_event(event):
        flash("You do not have permission to view that event.", "error")
        return redirect(url_for("events.index"))
    return render_template("events/detail.html", event=event)


@events_bp.route("/<int:event_id>/equipment-sheet")
@role_required("Admin", "Teacher", "Stage Manager")
def equipment_sheet(event_id):
    event = Event.query.get_or_404(event_id)
    settings = get_system_settings()
    if not role_meets_requirement(current_user().role, settings.pdf_export_permission_role):
        flash("You do not have permission to view event paperwork.", "error")
        return redirect(url_for("events.detail", event_id=event.id))
    linked_checkouts = sorted(event.checkouts, key=lambda checkout: checkout.equipment.name.lower())
    if settings.event_equipment_sheet_scope == "checked_out_only":
        linked_checkouts = [checkout for checkout in linked_checkouts if checkout.return_time is None]
    return render_template("events/equipment_sheet.html", event=event, linked_checkouts=linked_checkouts, generated_at=datetime.now())


@events_bp.route("/<int:event_id>/equipment-sheet.pdf")
@role_required("Admin", "Teacher", "Stage Manager")
def equipment_sheet_pdf(event_id):
    event = Event.query.get_or_404(event_id)
    settings = get_system_settings()
    if not role_meets_requirement(current_user().role, settings.pdf_export_permission_role):
        flash("You do not have permission to export event paperwork.", "error")
        return redirect(url_for("events.detail", event_id=event.id))
    linked_checkouts = sorted(event.checkouts, key=lambda checkout: checkout.equipment.name.lower())
    if settings.event_equipment_sheet_scope == "checked_out_only":
        linked_checkouts = [checkout for checkout in linked_checkouts if checkout.return_time is None]
    pdf_buffer, filename = build_event_equipment_pdf(event, linked_checkouts, datetime.now())
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@events_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    if request.method == "POST":
        assignment_rows = blank_assignment_rows()
        try:
            assignment_rows = submitted_assignment_rows()
            event = Event(
                name=request.form.get("name", "").strip(),
                venue=request.form.get("venue", "").strip(),
                description=request.form.get("description", "").strip(),
                event_date=parse_datetime(request.form.get("event_date")),
                setup_time=parse_datetime(request.form.get("setup_time")),
                packdown_time=parse_datetime(request.form.get("packdown_time")),
                created_by=current_user().id,
            )
        except ValueError as exc:
            flash(str(exc) if str(exc) else "Please enter valid event dates and times.", "error")
            return render_template("events/form.html", event=None, assignment_rows=assignment_rows, venue_options=event_venues(), crew_role_options=event_crew_roles())

        if not event.name or not event.venue or not event.event_date:
            flash("Name, venue, and event date are required.", "error")
        else:
            db.session.add(event)
            notification_plan = sync_event_assignments(event, assignment_rows)
            db.session.commit()
            notices = send_assignment_notifications(event, notification_plan)
            if notices:
                for notice in notices:
                    flash(notice, "error")
            flash("Event created.", "success")
            return redirect(url_for("events.index"))

    return render_template("events/form.html", event=None, assignment_rows=blank_assignment_rows(), venue_options=event_venues(), crew_role_options=event_crew_roles())


@events_bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(event_id):
    event = Event.query.get_or_404(event_id)

    if request.method == "POST":
        assignment_rows = blank_assignment_rows()
        try:
            assignment_rows = submitted_assignment_rows()
            event.name = request.form.get("name", "").strip()
            event.venue = request.form.get("venue", "").strip()
            event.description = request.form.get("description", "").strip()
            event.event_date = parse_datetime(request.form.get("event_date"))
            event.setup_time = parse_datetime(request.form.get("setup_time"))
            event.packdown_time = parse_datetime(request.form.get("packdown_time"))
        except ValueError as exc:
            flash(str(exc) if str(exc) else "Please enter valid event dates and times.", "error")
            return render_template("events/form.html", event=event, assignment_rows=assignment_rows, venue_options=event_venues(), crew_role_options=event_crew_roles())

        if not event.name or not event.venue or not event.event_date:
            flash("Name, venue, and event date are required.", "error")
        else:
            notification_plan = sync_event_assignments(event, assignment_rows)
            db.session.commit()
            notices = send_assignment_notifications(event, notification_plan)
            if notices:
                for notice in notices:
                    flash(notice, "error")
            flash("Event updated.", "success")
            return redirect(url_for("events.index"))

    return render_template("events/form.html", event=event, assignment_rows=existing_assignment_rows(event), venue_options=event_venues(), crew_role_options=event_crew_roles())


@events_bp.route("/<int:event_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("events.index"))
