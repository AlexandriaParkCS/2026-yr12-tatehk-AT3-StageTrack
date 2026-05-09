from pathlib import Path

from flask import Flask, redirect, render_template, session, url_for
from flask import flash, request
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from .admin import admin_bp
from .auth import auth_bp
from .config import Config
from .email_service import send_enquiry_email
from .equipment import equipment_bp
from .events import events_bp
from .extensions import db
from .models import Event, Equipment, Task, User
from .site_service import get_site_settings
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

        try:
            sent = send_enquiry_email(
                site_settings.enquiry_recipient_email,
                {
                    "name": name,
                    "email": email,
                    "contact": contact,
                    "use_case": use_case,
                    "message": message,
                },
            )
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
        task_snapshot_query = Task.query

        if user.role not in {"Admin", "Teacher", "Stage Manager"}:
            task_snapshot_query = task_snapshot_query.filter_by(assigned_to=user_id)

        stats = {
            "equipment_total": Equipment.query.count(),
            "missing_items": Equipment.query.filter_by(status="Missing").count(),
            "upcoming_events": Event.query.order_by(Event.event_date.asc()).limit(5).all(),
            "open_tasks": Task.query.filter(Task.status != "Completed").count(),
            "task_snapshot": task_snapshot_query.order_by(Task.due_time.asc(), Task.created_at.desc()).limit(5).all(),
        }
        return render_template("dashboard.html", stats=stats)

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        print("Database tables created.")

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
        db.session.commit()

    if "site_settings" in table_names:
        site_columns = {column["name"] for column in inspector.get_columns("site_settings")}
        if "enquiry_recipient_email" not in site_columns:
            db.session.execute(text("ALTER TABLE site_settings ADD COLUMN enquiry_recipient_email VARCHAR(255)"))
            db.session.commit()


app = create_app()
