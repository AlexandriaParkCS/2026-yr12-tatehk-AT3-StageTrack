from datetime import datetime

from .extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False, default="Viewer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tasks = db.relationship("Task", back_populates="assignee", lazy=True)
    checkouts = db.relationship("EquipmentCheckout", back_populates="user", lazy=True)
    damage_reports = db.relationship("DamageReport", back_populates="reporter", lazy=True)
    password_reset_tokens = db.relationship("PasswordResetToken", back_populates="user", lazy=True)


class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text)
    serial_number = db.Column(db.String(120), unique=True)
    qr_code = db.Column(db.String(255))
    condition = db.Column(db.String(80), default="Good")
    location = db.Column(db.String(120))
    status = db.Column(db.String(80), nullable=False, default="Available")
    image_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    checkouts = db.relationship("EquipmentCheckout", back_populates="equipment", lazy=True)
    damage_reports = db.relationship("DamageReport", back_populates="equipment", lazy=True)


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    venue = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.DateTime, nullable=False)
    setup_time = db.Column(db.DateTime)
    packdown_time = db.Column(db.DateTime)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))

    tasks = db.relationship("Task", back_populates="event", lazy=True)
    checklist_items = db.relationship("ChecklistItem", back_populates="event", lazy=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default="Pending")
    due_time = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event", back_populates="tasks")
    assignee = db.relationship("User", back_populates="tasks")


class EquipmentCheckout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    checkout_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    return_time = db.Column(db.DateTime)
    status = db.Column(db.String(50), nullable=False, default="Checked Out")

    equipment = db.relationship("Equipment", back_populates="checkouts")
    user = db.relationship("User", back_populates="checkouts")


class DamageReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    reported_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(255))
    status = db.Column(db.String(50), nullable=False, default="Open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    equipment = db.relationship("Equipment", back_populates="damage_reports")
    reporter = db.relationship("User", back_populates="damage_reports")


class ChecklistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"))

    event = db.relationship("Event", back_populates="checklist_items")


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", back_populates="password_reset_tokens")


class EmailSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    smtp_host = db.Column(db.String(255), nullable=False, default="")
    smtp_port = db.Column(db.Integer, nullable=False, default=587)
    smtp_use_tls = db.Column(db.Boolean, nullable=False, default=True)
    smtp_username = db.Column(db.String(255), default="")
    smtp_password = db.Column(db.String(255), default="")
    smtp_from_email = db.Column(db.String(255), nullable=False, default="")
    smtp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
