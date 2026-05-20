from datetime import datetime

from .extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    phone_number = db.Column(db.String(50))
    contact_details = db.Column(db.Text)
    role = db.Column(db.String(50), nullable=False, default="Viewer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tasks = db.relationship("Task", back_populates="assignee", lazy=True)
    checkouts = db.relationship("EquipmentCheckout", back_populates="user", lazy=True)
    damage_reports = db.relationship("DamageReport", back_populates="reporter", lazy=True)
    password_reset_tokens = db.relationship("PasswordResetToken", back_populates="user", lazy=True)
    event_assignments = db.relationship("EventCrewAssignment", back_populates="user", lazy=True)
    scan_logs = db.relationship("ScanLog", back_populates="user", lazy=True)


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
    kit_links = db.relationship("EquipmentKitItem", back_populates="equipment", cascade="all, delete-orphan", lazy=True)
    scan_logs = db.relationship("ScanLog", back_populates="equipment", lazy=True)


class StorageLocation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    shelf = db.Column(db.String(120))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def label(self):
        if self.shelf:
            return f"{self.name} - {self.shelf}"
        return self.name


class EquipmentKit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    items = db.relationship("EquipmentKitItem", back_populates="kit", cascade="all, delete-orphan", lazy=True)
    scan_logs = db.relationship("ScanLog", back_populates="kit", lazy=True)


class EquipmentKitItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kit_id = db.Column(db.Integer, db.ForeignKey("equipment_kit.id"), nullable=False)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)

    kit = db.relationship("EquipmentKit", back_populates="items")
    equipment = db.relationship("Equipment", back_populates="kit_links")


class ScanLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"))
    kit_id = db.Column(db.Integer, db.ForeignKey("equipment_kit.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    source = db.Column(db.String(50), nullable=False, default="public_camera")
    destination = db.Column(db.String(50), nullable=False, default="public_page")
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    equipment = db.relationship("Equipment", back_populates="scan_logs")
    kit = db.relationship("EquipmentKit", back_populates="scan_logs")
    user = db.relationship("User", back_populates="scan_logs")


class ConsumableItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    location = db.Column(db.String(120))
    unit_label = db.Column(db.String(40), nullable=False, default="units")
    quantity_on_hand = db.Column(db.Integer, nullable=False, default=0)
    reorder_level = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    adjustments = db.relationship("ConsumableAdjustment", back_populates="consumable", cascade="all, delete-orphan", lazy=True)


class ConsumableAdjustment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    consumable_id = db.Column(db.Integer, db.ForeignKey("consumable_item.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    quantity_change = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    consumable = db.relationship("ConsumableItem", back_populates="adjustments")
    user = db.relationship("User")


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
    checkouts = db.relationship("EquipmentCheckout", back_populates="event", lazy=True)
    crew_assignments = db.relationship(
        "EventCrewAssignment",
        back_populates="event",
        cascade="all, delete-orphan",
        lazy=True,
    )


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default="Pending")
    due_time = db.Column(db.DateTime)
    overdue_notified_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event", back_populates="tasks")
    assignee = db.relationship("User", back_populates="tasks")


class EquipmentCheckout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"))
    checkout_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    due_at = db.Column(db.DateTime)
    overdue_notified_at = db.Column(db.DateTime)
    return_time = db.Column(db.DateTime)
    status = db.Column(db.String(50), nullable=False, default="Checked Out")

    equipment = db.relationship("Equipment", back_populates="checkouts")
    user = db.relationship("User", back_populates="checkouts")
    event = db.relationship("Event", back_populates="checkouts")


class EventCrewAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("event.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    crew_email = db.Column(db.String(255), nullable=False, default="")
    crew_role = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    event = db.relationship("Event", back_populates="crew_assignments")
    user = db.relationship("User", back_populates="event_assignments")


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
    smtp_from_reset_email = db.Column(db.String(255), nullable=False, default="")
    smtp_from_welcome_email = db.Column(db.String(255), nullable=False, default="")
    smtp_from_equipment_email = db.Column(db.String(255), nullable=False, default="")
    notify_equipment_checkout = db.Column(db.Boolean, nullable=False, default=True)
    notify_equipment_overdue = db.Column(db.Boolean, nullable=False, default=True)
    notify_equipment_return = db.Column(db.Boolean, nullable=False, default=True)
    smtp_enabled = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    coming_soon_enabled = db.Column(db.Boolean, nullable=False, default=True)
    enquiry_recipient_email = db.Column(db.String(255))
    maintenance_mode_message = db.Column(db.Text)
    announcement_banner_enabled = db.Column(db.Boolean, nullable=False, default=False)
    announcement_banner_text = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    school_name = db.Column(db.String(255), nullable=False, default="StageTrack")
    support_email = db.Column(db.String(255), default="")
    timezone_name = db.Column(db.String(100), nullable=False, default="Australia/Sydney")
    datetime_format = db.Column(db.String(100), nullable=False, default="%d %b %Y %I:%M %p")

    student_crew_can_view_all_events = db.Column(db.Boolean, nullable=False, default=False)
    student_crew_can_view_all_equipment = db.Column(db.Boolean, nullable=False, default=True)
    checkout_permission_role = db.Column(db.String(50), nullable=False, default="Stage Manager")
    maintenance_submit_permission_role = db.Column(db.String(50), nullable=False, default="Student Crew")
    consumable_manage_permission_role = db.Column(db.String(50), nullable=False, default="Stage Manager")
    pdf_export_permission_role = db.Column(db.String(50), nullable=False, default="Stage Manager")

    equipment_categories = db.Column(db.Text, nullable=False, default="")
    equipment_statuses = db.Column(db.Text, nullable=False, default="")
    serial_numbers_required = db.Column(db.Boolean, nullable=False, default=False)
    due_dates_required = db.Column(db.Boolean, nullable=False, default=False)
    due_soon_hours = db.Column(db.Integer, nullable=False, default=24)
    long_overdue_days = db.Column(db.Integer, nullable=False, default=7)
    auto_hide_removed_items = db.Column(db.Boolean, nullable=False, default=True)
    scan_summary_window_hours = db.Column(db.Integer, nullable=False, default=24)
    public_qr_show_description = db.Column(db.Boolean, nullable=False, default=True)
    public_qr_show_location = db.Column(db.Boolean, nullable=False, default=True)
    public_qr_show_checkout_state = db.Column(db.Boolean, nullable=False, default=True)
    public_qr_show_maintenance = db.Column(db.Boolean, nullable=False, default=True)

    event_venues = db.Column(db.Text, nullable=False, default="")
    event_crew_roles = db.Column(db.Text, nullable=False, default="")
    auto_send_event_invites = db.Column(db.Boolean, nullable=False, default=True)
    event_equipment_sheet_scope = db.Column(db.String(50), nullable=False, default="all_linked")

    consumable_categories = db.Column(db.Text, nullable=False, default="")
    low_stock_alert_behavior = db.Column(db.String(50), nullable=False, default="at_or_below")
    students_can_log_consumables = db.Column(db.Boolean, nullable=False, default=True)
    negative_consumable_adjustments_manager_only = db.Column(db.Boolean, nullable=False, default=True)

    overdue_alert_recipients = db.Column(db.Text, nullable=False, default="")
    maintenance_alert_recipients = db.Column(db.Text, nullable=False, default="")
    enquiry_alert_recipients = db.Column(db.Text, nullable=False, default="")
    low_stock_alert_recipients = db.Column(db.Text, nullable=False, default="")
    password_reset_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack Password Reset")
    welcome_email_subject = db.Column(db.String(255), nullable=False, default="Welcome to StageTrack")
    equipment_checkout_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack equipment checked out: {equipment_name}")
    equipment_overdue_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack equipment overdue: {equipment_name}")
    equipment_return_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack equipment returned: {equipment_name}")
    maintenance_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack maintenance request: {equipment_name}")
    enquiry_email_subject = db.Column(db.String(255), nullable=False, default="StageTrack enquiry from {name}")

    maintenance_statuses = db.Column(db.Text, nullable=False, default="")
    resolved_visible_in_queue = db.Column(db.Boolean, nullable=False, default=False)
    maintenance_resolve_permission_role = db.Column(db.String(50), nullable=False, default="Teacher")
    repeat_damage_threshold = db.Column(db.Integer, nullable=False, default=2)

    pdf_paper_size = db.Column(db.String(20), nullable=False, default="A4")
    pdf_show_header = db.Column(db.Boolean, nullable=False, default=True)
    pdf_header_text = db.Column(db.String(255), nullable=False, default="StageTrack")
    pdf_footer_text = db.Column(db.String(255), nullable=False, default="Generated by StageTrack")
    pdf_include_checkboxes = db.Column(db.Boolean, nullable=False, default=True)
    pdf_include_notes = db.Column(db.Boolean, nullable=False, default=True)
    pdf_include_signatures = db.Column(db.Boolean, nullable=False, default=False)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
