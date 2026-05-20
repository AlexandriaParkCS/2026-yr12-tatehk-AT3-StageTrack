from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, redirect, render_template, session, url_for
from flask import flash, request
from sqlalchemy import case, inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from .admin import admin_bp
from .auth import auth_bp
from .config import Config
from .email_service import send_enquiry_email, send_equipment_overdue_email, send_task_overdue_email
from .equipment import equipment_bp
from .events import events_bp
from .extensions import db
from .models import ConsumableAdjustment, ConsumableItem, EquipmentCheckout, EquipmentKit, EquipmentKitItem, Event, EventCrewAssignment, Equipment, ScanLog, StorageLocation, SystemSettings, Task, User
from .site_service import get_site_settings
from .system_settings_service import alert_recipient_list, format_datetime_for_display, get_system_settings
from .tasks import tasks_bp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["QR_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(tasks_bp)

    @app.before_request
    def require_password_change():
        user_id = session.get("user_id")
        if not user_id:
            return None

        if request.endpoint in {
            "auth.force_password_change",
            "auth.logout",
            "static",
        }:
            return None

        user = db.session.get(User, user_id)
        if user and user.must_change_password:
            return redirect(url_for("auth.force_password_change"))

        return None

    @app.before_request
    def send_pending_overdue_emails():
        overdue_checkouts = EquipmentCheckout.query.filter(
            EquipmentCheckout.return_time.is_(None),
            EquipmentCheckout.due_at.is_not(None),
            EquipmentCheckout.overdue_notified_at.is_(None),
            EquipmentCheckout.due_at < datetime.now(),
        ).all()

        for checkout in overdue_checkouts:
            try:
                sent = send_equipment_overdue_email(checkout)
            except Exception:
                sent = False
            if sent:
                checkout.overdue_notified_at = datetime.utcnow()

        if overdue_checkouts:
            db.session.commit()

    @app.before_request
    def send_pending_task_overdue_emails():
        overdue_tasks = Task.query.filter(
            Task.status != "Completed",
            Task.due_time.is_not(None),
            Task.overdue_notified_at.is_(None),
            Task.due_time < datetime.now(),
        ).all()

        for task in overdue_tasks:
            try:
                sent = send_task_overdue_email(task)
            except Exception:
                sent = False
            if sent:
                task.overdue_notified_at = datetime.utcnow()

        if overdue_tasks:
            db.session.commit()

    @app.route("/")
    def home():
        if session.get("user_id"):
            return redirect(url_for("dashboard"))
        site_settings = get_site_settings()
        if site_settings.coming_soon_enabled:
            return render_template("landing.html")
        return render_template("public_home.html")

    @app.route("/enquire", methods=["POST"])
    def enquire():
        site_settings = get_site_settings()
        if site_settings.coming_soon_enabled:
            return redirect(url_for("home"))

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        contact = request.form.get("contact", "").strip()
        use_case = request.form.get("use_case", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not email or not contact or not use_case:
            flash("Please complete all required enquiry fields.", "error")
            return redirect(url_for("home"))

        if not site_settings.enquiry_recipient_email:
            flash("Enquiry email is not configured in site settings yet.", "error")
            return redirect(url_for("home"))

        system_settings = get_system_settings()
        recipients = [site_settings.enquiry_recipient_email] + alert_recipient_list(system_settings.enquiry_alert_recipients)
        recipients = list(dict.fromkeys([email for email in recipients if email]))
        try:
            sent = False
            payload = {
                "name": name,
                "email": email,
                "contact": contact,
                "use_case": use_case,
                "message": message,
            }
            for recipient in recipients:
                sent = send_enquiry_email(recipient, payload) or sent
        except Exception as exc:
            flash(f"Enquiry could not be sent right now: {exc}", "error")
            return redirect(url_for("home"))

        if not sent:
            flash("Email sending is not configured yet, so the enquiry could not be sent.", "error")
        else:
            flash("Your enquiry has been sent. We will be in touch soon.", "success")

        return redirect(url_for("home"))

    @app.route("/dashboard")
    def dashboard():
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))

        user_id = session["user_id"]
        user = db.session.get(User, user_id)
        task_snapshot_query = Task.query.filter(Task.status != "Completed")
        upcoming_events_query = Event.query.order_by(Event.event_date.asc())
        local_now = datetime.now()
        overdue_query = EquipmentCheckout.query.filter(
            EquipmentCheckout.return_time.is_(None),
            EquipmentCheckout.due_at.is_not(None),
            EquipmentCheckout.due_at < local_now,
        )
        broken_query = Equipment.query.filter(Equipment.status.in_(["Damaged", "Under Repair"]))
        system_settings = get_system_settings()
        due_soon_threshold = local_now + timedelta(hours=max(1, system_settings.due_soon_hours))

        if user.role not in {"Admin", "Teacher", "Stage Manager"}:
            task_snapshot_query = task_snapshot_query.filter_by(assigned_to=user_id)
            overdue_query = overdue_query.filter_by(user_id=user_id)
        if user.role == "Student Crew":
            upcoming_events_query = upcoming_events_query.join(EventCrewAssignment).filter(EventCrewAssignment.user_id == user_id)

        if user.role not in {"Admin", "Teacher"}:
            broken_items = 0
            broken_snapshot = []
        else:
            broken_items = broken_query.count()
            broken_snapshot = broken_query.order_by(Equipment.name.asc()).limit(5).all()

        if user.role not in {"Admin", "Teacher", "Stage Manager"}:
            due_soon_alerts = []
            long_overdue_alerts = []
            repeat_damage_alerts = []
            event_end_alerts = []
            manager_event_task_summary = []
            crew_without_tasks = []
        else:
            active_checkouts = EquipmentCheckout.query.filter(EquipmentCheckout.return_time.is_(None)).all()
            due_soon_alerts = sorted(
                [
                    checkout
                    for checkout in active_checkouts
                    if checkout.due_at and local_now <= checkout.due_at <= due_soon_threshold
                ],
                key=lambda checkout: checkout.due_at,
            )[:5]
            long_overdue_alerts = sorted(
                [
                    checkout
                    for checkout in active_checkouts
                    if checkout.due_at and checkout.due_at <= (local_now - timedelta(days=max(1, system_settings.long_overdue_days)))
                ],
                key=lambda checkout: checkout.due_at,
            )[:5]
            repeat_damage_alerts = [
                item
                for item in Equipment.query.filter(Equipment.status != "Removed").order_by(Equipment.name.asc()).all()
                if len(item.damage_reports) >= max(1, system_settings.repeat_damage_threshold)
            ][:5]
            event_end_alerts = sorted(
                [
                    checkout
                    for checkout in active_checkouts
                    if checkout.event
                    and ((checkout.event.packdown_time and checkout.event.packdown_time < local_now) or checkout.event.event_date < local_now)
                ],
                key=lambda checkout: checkout.event.packdown_time or checkout.event.event_date,
            )[:5]
            manager_event_task_summary = []
            for event in Event.query.order_by(Event.event_date.asc()).all():
                total_tasks = len(event.tasks)
                incomplete_tasks = [task for task in event.tasks if task.status != "Completed"]
                if total_tasks or incomplete_tasks:
                    completion_rate = int(round(((total_tasks - len(incomplete_tasks)) / total_tasks) * 100)) if total_tasks else 0
                    manager_event_task_summary.append(
                        {
                            "event": event,
                            "total_tasks": total_tasks,
                            "incomplete_count": len(incomplete_tasks),
                            "overdue_count": sum(1 for task in incomplete_tasks if task.due_time and task.due_time < local_now),
                            "completion_rate": completion_rate,
                        }
                    )
            manager_event_task_summary = manager_event_task_summary[:5]
            crew_without_tasks = []
            for event in Event.query.order_by(Event.event_date.asc()).all():
                assigned_ids = {task.assigned_to for task in event.tasks}
                waiting_crew = [assignment for assignment in event.crew_assignments if assignment.user_id not in assigned_ids]
                if waiting_crew:
                    crew_without_tasks.append({"event": event, "crew": waiting_crew})
            crew_without_tasks = crew_without_tasks[:5]

        if user.role in {"Student Crew", "Viewer"}:
            assignment_upcoming_events = (
                EventCrewAssignment.query.join(Event)
                .filter(EventCrewAssignment.user_id == user_id)
                .order_by(Event.event_date.asc())
                .limit(5)
                .all()
            )
        else:
            assignment_upcoming_events = []

        stats = {
            "equipment_total": Equipment.query.filter(Equipment.status != "Removed").count(),
            "kit_total": EquipmentKit.query.count(),
            "low_stock_consumables": ConsumableItem.query.filter(ConsumableItem.quantity_on_hand <= ConsumableItem.reorder_level).count(),
            "missing_items": Equipment.query.filter_by(status="Missing").count(),
            "broken_items": broken_items,
            "broken_snapshot": broken_snapshot,
            "upcoming_events": assignment_upcoming_events if assignment_upcoming_events else upcoming_events_query.limit(5).all(),
            "open_tasks": Task.query.filter(Task.status != "Completed").count(),
            "overdue_items": overdue_query.count(),
            "overdue_checkouts": overdue_query.order_by(EquipmentCheckout.due_at.asc()).limit(5).all(),
            "due_soon_alerts": due_soon_alerts,
            "long_overdue_alerts": long_overdue_alerts,
            "repeat_damage_alerts": repeat_damage_alerts,
            "event_end_alerts": event_end_alerts,
            "task_snapshot": task_snapshot_query.order_by(
                case(
                    (Task.status == "In Progress", 0),
                    (Task.status == "Pending", 1),
                    else_=2,
                ),
                Task.due_time.asc(),
                Task.created_at.desc(),
            ).limit(5).all(),
            "recent_scans": [],
            "scan_summary": None,
            "due_soon_tasks": [],
            "overdue_tasks": [],
            "my_events": [],
            "my_equipment": [],
            "manager_event_task_summary": manager_event_task_summary,
            "crew_without_tasks": crew_without_tasks,
        }

        if user.role in {"Admin", "Teacher", "Stage Manager"}:
            recent_scan_logs = ScanLog.query.order_by(ScanLog.scanned_at.desc()).limit(6).all()
            summary_cutoff = datetime.utcnow() - timedelta(hours=max(1, system_settings.scan_summary_window_hours))
            summary_logs = ScanLog.query.filter(ScanLog.scanned_at >= summary_cutoff).all()
            stats["recent_scans"] = recent_scan_logs
            stats["scan_summary"] = {
                "window_hours": max(1, system_settings.scan_summary_window_hours),
                "total": len(summary_logs),
                "public": sum(1 for log in summary_logs if log.source == "public_camera"),
                "app": sum(1 for log in summary_logs if log.source == "app_scanner"),
                "manual": sum(1 for log in summary_logs if log.source == "manual_entry"),
            }
        else:
            user_tasks = Task.query.filter_by(assigned_to=user_id).order_by(Task.due_time.asc(), Task.created_at.desc()).all()
            due_soon_limit = local_now + timedelta(hours=max(1, system_settings.due_soon_hours))
            stats["due_soon_tasks"] = [
                task for task in user_tasks
                if task.status != "Completed" and task.due_time and local_now <= task.due_time <= due_soon_limit
            ][:5]
            stats["overdue_tasks"] = [
                task for task in user_tasks
                if task.status != "Completed" and task.due_time and task.due_time < local_now
            ][:5]
            stats["my_events"] = [
                assignment for assignment in EventCrewAssignment.query.join(Event).filter(EventCrewAssignment.user_id == user_id).order_by(Event.event_date.asc()).all()
            ][:5]
            stats["my_equipment"] = EquipmentCheckout.query.filter_by(user_id=user_id, return_time=None).order_by(EquipmentCheckout.checkout_time.desc()).limit(5).all()
        return render_template("dashboard.html", stats=stats)

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        print("Database tables created.")

    @app.context_processor
    def inject_system_settings():
        settings = get_system_settings()
        return {
            "system_settings": settings,
            "format_dt": format_datetime_for_display,
        }

    @app.context_processor
    def inject_site_settings():
        return {
            "site_settings": get_site_settings(),
        }

    @app.template_filter("app_dt")
    def app_dt_filter(value):
        return format_datetime_for_display(value)

    with app.app_context():
        db.create_all()
        ensure_schema_updates()

    return app


def ensure_schema_updates():
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    if "user" not in table_names:
        return

    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "is_active" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
    if "must_change_password" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0"))
    if "phone_number" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN phone_number VARCHAR(50)"))
    if "contact_details" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN contact_details TEXT"))
    db.session.commit()

    if "email_settings" in table_names:
        email_columns = {column["name"] for column in inspector.get_columns("email_settings")}
        if "smtp_from_reset_email" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN smtp_from_reset_email VARCHAR(255) NOT NULL DEFAULT ''"))
        if "smtp_from_welcome_email" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN smtp_from_welcome_email VARCHAR(255) NOT NULL DEFAULT ''"))
        if "smtp_from_equipment_email" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN smtp_from_equipment_email VARCHAR(255) NOT NULL DEFAULT ''"))
        if "notify_equipment_checkout" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN notify_equipment_checkout BOOLEAN NOT NULL DEFAULT 1"))
        if "notify_equipment_overdue" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN notify_equipment_overdue BOOLEAN NOT NULL DEFAULT 1"))
        if "notify_equipment_return" not in email_columns:
            db.session.execute(text("ALTER TABLE email_settings ADD COLUMN notify_equipment_return BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()

    if "site_settings" in table_names:
        site_columns = {column["name"] for column in inspector.get_columns("site_settings")}
        if "enquiry_recipient_email" not in site_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN enquiry_recipient_email VARCHAR(255)"))
        if "maintenance_mode_message" not in site_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN maintenance_mode_message TEXT"))
        if "announcement_banner_enabled" not in site_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN announcement_banner_enabled BOOLEAN NOT NULL DEFAULT 0"))
        if "announcement_banner_text" not in site_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN announcement_banner_text TEXT"))
        db.session.commit()

    if "equipment_checkout" in table_names:
        checkout_columns = {column["name"] for column in inspector.get_columns("equipment_checkout")}
        if "event_id" not in checkout_columns:
            db.session.execute(text("ALTER TABLE equipment_checkout ADD COLUMN event_id INTEGER"))
        if "due_at" not in checkout_columns:
            db.session.execute(text("ALTER TABLE equipment_checkout ADD COLUMN due_at DATETIME"))
        if "overdue_notified_at" not in checkout_columns:
            db.session.execute(text("ALTER TABLE equipment_checkout ADD COLUMN overdue_notified_at DATETIME"))
        db.session.commit()

    if "task" in table_names:
        task_columns = {column["name"] for column in inspector.get_columns("task")}
        if "overdue_notified_at" not in task_columns:
            db.session.execute(text("ALTER TABLE task ADD COLUMN overdue_notified_at DATETIME"))
            db.session.commit()

    if "event_crew_assignment" in table_names:
        assignment_columns = {column["name"] for column in inspector.get_columns("event_crew_assignment")}
        if "crew_email" not in assignment_columns:
            db.session.execute(text("ALTER TABLE event_crew_assignment ADD COLUMN crew_email VARCHAR(255) NOT NULL DEFAULT ''"))
            db.session.commit()

    if "system_settings" in table_names:
        system_columns = {column["name"] for column in inspector.get_columns("system_settings")}
        if "scan_summary_window_hours" not in system_columns:
            db.session.execute(text("ALTER TABLE system_settings ADD COLUMN scan_summary_window_hours INTEGER NOT NULL DEFAULT 24"))
        if "public_qr_show_description" not in system_columns:
            db.session.execute(text("ALTER TABLE system_settings ADD COLUMN public_qr_show_description BOOLEAN NOT NULL DEFAULT 1"))
        if "public_qr_show_location" not in system_columns:
            db.session.execute(text("ALTER TABLE system_settings ADD COLUMN public_qr_show_location BOOLEAN NOT NULL DEFAULT 1"))
        if "public_qr_show_checkout_state" not in system_columns:
            db.session.execute(text("ALTER TABLE system_settings ADD COLUMN public_qr_show_checkout_state BOOLEAN NOT NULL DEFAULT 1"))
        if "public_qr_show_maintenance" not in system_columns:
            db.session.execute(text("ALTER TABLE system_settings ADD COLUMN public_qr_show_maintenance BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()

    if "storage_location" not in table_names:
        StorageLocation.__table__.create(db.engine)
    if "equipment_kit" not in table_names:
        EquipmentKit.__table__.create(db.engine)
    if "equipment_kit_item" not in table_names:
        EquipmentKitItem.__table__.create(db.engine)
    if "consumable_item" not in table_names:
        ConsumableItem.__table__.create(db.engine)
    if "consumable_adjustment" not in table_names:
        ConsumableAdjustment.__table__.create(db.engine)
    if "system_settings" not in table_names:
        SystemSettings.__table__.create(db.engine)
    if "scan_log" not in table_names:
        ScanLog.__table__.create(db.engine)


app = create_app()
