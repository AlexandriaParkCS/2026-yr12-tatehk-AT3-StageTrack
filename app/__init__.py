from pathlib import Path

from flask import Flask, redirect, render_template, session, url_for
from sqlalchemy import inspect, text

from .admin import admin_bp
from .auth import auth_bp
from .config import Config
from .equipment import equipment_bp
from .events import events_bp
from .extensions import db
from .models import Event, Equipment, Task, User
from .tasks import tasks_bp


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
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
        return render_template("landing.html")

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
    if "user" not in inspector.get_table_names():
        return

    user_columns = {column["name"] for column in inspector.get_columns("user")}
    if "is_active" not in user_columns:
        db.session.execute(text("ALTER TABLE user ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()
