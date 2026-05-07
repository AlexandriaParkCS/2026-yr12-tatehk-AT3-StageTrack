from datetime import datetime

from flask import flash, redirect, render_template, request, url_for

from ..auth.routes import current_user, login_required, role_required
from ..extensions import db
from ..models import Event
from . import events_bp


DATETIME_FORMAT = "%Y-%m-%dT%H:%M"


def parse_datetime(value):
    if not value:
        return None
    return datetime.strptime(value, DATETIME_FORMAT)


@events_bp.route("/")
@login_required
def index():
    events = Event.query.order_by(Event.event_date.asc()).all()
    return render_template("events/index.html", events=events)


@events_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    if request.method == "POST":
        try:
            event = Event(
                name=request.form.get("name", "").strip(),
                venue=request.form.get("venue", "").strip(),
                description=request.form.get("description", "").strip(),
                event_date=parse_datetime(request.form.get("event_date")),
                setup_time=parse_datetime(request.form.get("setup_time")),
                packdown_time=parse_datetime(request.form.get("packdown_time")),
                created_by=current_user().id,
            )
        except ValueError:
            flash("Please enter valid event dates and times.", "error")
            return render_template("events/form.html", event=None)

        if not event.name or not event.venue or not event.event_date:
            flash("Name, venue, and event date are required.", "error")
        else:
            db.session.add(event)
            db.session.commit()
            flash("Event created.", "success")
            return redirect(url_for("events.index"))

    return render_template("events/form.html", event=None)


@events_bp.route("/<int:event_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(event_id):
    event = Event.query.get_or_404(event_id)

    if request.method == "POST":
        try:
            event.name = request.form.get("name", "").strip()
            event.venue = request.form.get("venue", "").strip()
            event.description = request.form.get("description", "").strip()
            event.event_date = parse_datetime(request.form.get("event_date"))
            event.setup_time = parse_datetime(request.form.get("setup_time"))
            event.packdown_time = parse_datetime(request.form.get("packdown_time"))
        except ValueError:
            flash("Please enter valid event dates and times.", "error")
            return render_template("events/form.html", event=event)

        if not event.name or not event.venue or not event.event_date:
            flash("Name, venue, and event date are required.", "error")
        else:
            db.session.commit()
            flash("Event updated.", "success")
            return redirect(url_for("events.index"))

    return render_template("events/form.html", event=event)


@events_bp.route("/<int:event_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(event_id):
    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    flash("Event deleted.", "success")
    return redirect(url_for("events.index"))
