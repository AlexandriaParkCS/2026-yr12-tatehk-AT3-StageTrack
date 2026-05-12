from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from ..auth.routes import ROLES, current_user, role_required
from ..email_service import (
    build_password_reset_url,
    deliver_email,
    get_email_settings,
    issue_password_reset_token,
    send_password_reset_email,
    send_welcome_email,
)
from ..extensions import db
from ..models import Equipment, PasswordResetToken, StorageLocation, User
from ..site_service import get_site_settings
from ..system_settings_service import get_system_settings, settings_role_options
from . import admin_bp


def can_delete_user(user):
    if user.role == "Admin" and User.query.filter_by(role="Admin", is_active=True).count() <= 1:
        return False, "You cannot delete the last active admin account."
    if user.tasks:
        return False, "This account cannot be deleted while tasks are still assigned to it."
    if user.checkouts:
        return False, "This account cannot be deleted while equipment checkout history is linked to it."
    if user.damage_reports:
        return False, "This account cannot be deleted while damage reports are linked to it."
    if user.event_assignments:
        return False, "This account cannot be deleted while event crew roles are linked to it."
    return True, None


@admin_bp.route("/users")
@role_required("Admin")
def users():
    user_list = User.query.order_by(User.created_at.asc(), User.name.asc()).all()
    latest_reset_token_id = request.args.get("token", type=int)
    latest_reset_token = None
    if latest_reset_token_id:
        latest_reset_token = db.session.get(PasswordResetToken, latest_reset_token_id)

    return render_template(
        "admin/users.html",
        users=user_list,
        roles=ROLES,
        latest_reset_token=latest_reset_token,
    )


@admin_bp.route("/users/<int:user_id>")
@role_required("Admin")
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    now = datetime.now()
    active_checkouts = [checkout for checkout in user.checkouts if checkout.return_time is None]
    overdue_checkouts = [checkout for checkout in active_checkouts if checkout.due_at and checkout.due_at < now]
    checkout_history = sorted(user.checkouts, key=lambda checkout: checkout.checkout_time, reverse=True)[:10]
    event_assignments = sorted(
        user.event_assignments,
        key=lambda assignment: assignment.event.event_date,
    )

    return render_template(
        "admin/user_detail.html",
        user=user,
        active_checkouts=active_checkouts,
        overdue_checkouts=overdue_checkouts,
        checkout_history=checkout_history,
        event_assignments=event_assignments,
        now=now,
    )


@admin_bp.route("/settings/email", methods=["GET", "POST"])
@role_required("Admin")
def email_settings():
    settings = get_email_settings()

    if request.method == "POST":
        settings.smtp_host = request.form.get("smtp_host", "").strip()
        settings.smtp_port = request.form.get("smtp_port", type=int) or 587
        settings.smtp_use_tls = request.form.get("smtp_use_tls") == "on"
        settings.smtp_username = request.form.get("smtp_username", "").strip()
        new_password = request.form.get("smtp_password", "")
        if new_password:
            settings.smtp_password = new_password
        settings.smtp_from_email = request.form.get("smtp_from_email", "").strip().lower()
        settings.smtp_from_reset_email = request.form.get("smtp_from_reset_email", "").strip().lower()
        settings.smtp_from_welcome_email = request.form.get("smtp_from_welcome_email", "").strip().lower()
        settings.smtp_from_equipment_email = request.form.get("smtp_from_equipment_email", "").strip().lower()
        settings.notify_equipment_checkout = request.form.get("notify_equipment_checkout") == "on"
        settings.notify_equipment_overdue = request.form.get("notify_equipment_overdue") == "on"
        settings.notify_equipment_return = request.form.get("notify_equipment_return") == "on"
        settings.smtp_enabled = request.form.get("smtp_enabled") == "on"
        db.session.commit()
        flash("Email settings saved.", "success")
        return redirect(url_for("admin.email_settings"))

    return render_template("admin/email_settings.html", settings=settings)


@admin_bp.route("/settings/site", methods=["GET", "POST"])
@role_required("Admin")
def site_settings():
    settings = get_site_settings()

    if request.method == "POST":
        settings.coming_soon_enabled = request.form.get("coming_soon_enabled") == "on"
        settings.enquiry_recipient_email = request.form.get("enquiry_recipient_email", "").strip().lower() or None
        settings.maintenance_mode_message = request.form.get("maintenance_mode_message", "").strip() or None
        settings.announcement_banner_enabled = request.form.get("announcement_banner_enabled") == "on"
        settings.announcement_banner_text = request.form.get("announcement_banner_text", "").strip() or None
        db.session.commit()
        flash("Site settings saved.", "success")
        return redirect(url_for("admin.site_settings"))

    return render_template("admin/site_settings.html", settings=settings)


@admin_bp.route("/settings/locations", methods=["GET", "POST"])
@role_required("Admin")
def location_settings():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        shelf = request.form.get("shelf", "").strip()
        notes = request.form.get("notes", "").strip()
        location_label = f"{name} - {shelf}" if shelf else name
        existing = [location for location in StorageLocation.query.order_by(StorageLocation.name.asc()).all() if location.label.lower() == location_label.lower()]

        if not name:
            flash("Location name is required.", "error")
        elif existing:
            flash("That location and shelf combination already exists.", "error")
        else:
            location = StorageLocation(
                name=name,
                shelf=shelf or None,
                notes=notes or None,
            )
            db.session.add(location)
            db.session.commit()
            flash("Storage location added.", "success")
            return redirect(url_for("admin.location_settings"))

    locations = StorageLocation.query.order_by(StorageLocation.name.asc(), StorageLocation.shelf.asc()).all()
    return render_template("admin/location_settings.html", locations=locations)


@admin_bp.route("/settings/system", methods=["GET", "POST"])
@role_required("Admin")
def system_settings():
    settings = get_system_settings()

    if request.method == "POST":
        settings.school_name = request.form.get("school_name", "").strip() or "StageTrack"
        settings.support_email = request.form.get("support_email", "").strip().lower()
        settings.timezone_name = request.form.get("timezone_name", "").strip() or "Australia/Sydney"
        settings.datetime_format = request.form.get("datetime_format", "").strip() or "%d %b %Y %I:%M %p"

        settings.student_crew_can_view_all_events = request.form.get("student_crew_can_view_all_events") == "on"
        settings.student_crew_can_view_all_equipment = request.form.get("student_crew_can_view_all_equipment") == "on"
        settings.checkout_permission_role = request.form.get("checkout_permission_role", "Stage Manager").strip()
        settings.maintenance_submit_permission_role = request.form.get("maintenance_submit_permission_role", "Student Crew").strip()
        settings.consumable_manage_permission_role = request.form.get("consumable_manage_permission_role", "Stage Manager").strip()
        settings.pdf_export_permission_role = request.form.get("pdf_export_permission_role", "Stage Manager").strip()

        settings.equipment_categories = request.form.get("equipment_categories", "").strip()
        settings.equipment_statuses = request.form.get("equipment_statuses", "").strip()
        settings.serial_numbers_required = request.form.get("serial_numbers_required") == "on"
        settings.due_dates_required = request.form.get("due_dates_required") == "on"
        settings.due_soon_hours = request.form.get("due_soon_hours", type=int) or 24
        settings.long_overdue_days = request.form.get("long_overdue_days", type=int) or 7
        settings.auto_hide_removed_items = request.form.get("auto_hide_removed_items") == "on"

        settings.event_venues = request.form.get("event_venues", "").strip()
        settings.event_crew_roles = request.form.get("event_crew_roles", "").strip()
        settings.auto_send_event_invites = request.form.get("auto_send_event_invites") == "on"
        settings.event_equipment_sheet_scope = request.form.get("event_equipment_sheet_scope", "all_linked").strip()

        settings.consumable_categories = request.form.get("consumable_categories", "").strip()
        settings.low_stock_alert_behavior = request.form.get("low_stock_alert_behavior", "at_or_below").strip()
        settings.students_can_log_consumables = request.form.get("students_can_log_consumables") == "on"
        settings.negative_consumable_adjustments_manager_only = request.form.get("negative_consumable_adjustments_manager_only") == "on"

        settings.overdue_alert_recipients = request.form.get("overdue_alert_recipients", "").strip()
        settings.maintenance_alert_recipients = request.form.get("maintenance_alert_recipients", "").strip()
        settings.enquiry_alert_recipients = request.form.get("enquiry_alert_recipients", "").strip()
        settings.low_stock_alert_recipients = request.form.get("low_stock_alert_recipients", "").strip()
        settings.password_reset_email_subject = request.form.get("password_reset_email_subject", "").strip() or settings.password_reset_email_subject
        settings.welcome_email_subject = request.form.get("welcome_email_subject", "").strip() or settings.welcome_email_subject
        settings.equipment_checkout_email_subject = request.form.get("equipment_checkout_email_subject", "").strip() or settings.equipment_checkout_email_subject
        settings.equipment_overdue_email_subject = request.form.get("equipment_overdue_email_subject", "").strip() or settings.equipment_overdue_email_subject
        settings.equipment_return_email_subject = request.form.get("equipment_return_email_subject", "").strip() or settings.equipment_return_email_subject
        settings.maintenance_email_subject = request.form.get("maintenance_email_subject", "").strip() or settings.maintenance_email_subject
        settings.enquiry_email_subject = request.form.get("enquiry_email_subject", "").strip() or settings.enquiry_email_subject

        settings.maintenance_statuses = request.form.get("maintenance_statuses", "").strip()
        settings.resolved_visible_in_queue = request.form.get("resolved_visible_in_queue") == "on"
        settings.maintenance_resolve_permission_role = request.form.get("maintenance_resolve_permission_role", "Teacher").strip()
        settings.repeat_damage_threshold = request.form.get("repeat_damage_threshold", type=int) or 2

        settings.pdf_paper_size = request.form.get("pdf_paper_size", "A4").strip()
        settings.pdf_show_header = request.form.get("pdf_show_header") == "on"
        settings.pdf_header_text = request.form.get("pdf_header_text", "").strip() or "StageTrack"
        settings.pdf_footer_text = request.form.get("pdf_footer_text", "").strip() or "Generated by StageTrack"
        settings.pdf_include_checkboxes = request.form.get("pdf_include_checkboxes") == "on"
        settings.pdf_include_notes = request.form.get("pdf_include_notes") == "on"
        settings.pdf_include_signatures = request.form.get("pdf_include_signatures") == "on"

        db.session.commit()
        flash("System settings saved.", "success")
        return redirect(url_for("admin.system_settings"))

    return render_template("admin/system_settings.html", settings=settings, role_options=settings_role_options())


@admin_bp.route("/settings/locations/<int:location_id>/toggle", methods=["POST"])
@role_required("Admin")
def toggle_location(location_id):
    location = StorageLocation.query.get_or_404(location_id)
    location.is_active = not location.is_active
    db.session.commit()
    flash("Storage location status updated.", "success")
    return redirect(url_for("admin.location_settings"))


@admin_bp.route("/settings/locations/<int:location_id>/delete", methods=["POST"])
@role_required("Admin")
def delete_location(location_id):
    location = StorageLocation.query.get_or_404(location_id)

    if Equipment.query.filter_by(location=location.label).count():
        flash("This location is still assigned to equipment. Move those items first before deleting it.", "error")
        return redirect(url_for("admin.location_settings"))

    db.session.delete(location)
    db.session.commit()
    flash("Storage location deleted.", "success")
    return redirect(url_for("admin.location_settings"))


@admin_bp.route("/settings/email/test", methods=["POST"])
@role_required("Admin")
def test_email_settings():
    settings = get_email_settings()
    recipient = request.form.get("test_email", "").strip().lower()

    if not recipient:
        flash("Enter an email address for the test message.", "error")
        return redirect(url_for("admin.email_settings"))

    try:
        sent = deliver_email(
            settings,
            recipient,
            "StageTrack SMTP Test",
            "This is a StageTrack SMTP test email. If you received it, the admin email settings are working.",
            email_type=request.form.get("email_type", "general"),
        )
    except Exception as exc:
        flash(f"Test email failed: {exc}", "error")
        return redirect(url_for("admin.email_settings"))

    if not sent:
        flash("Email sending is disabled or incomplete. Save valid SMTP settings first.", "error")
    else:
        flash("Test email sent successfully.", "success")

    return redirect(url_for("admin.email_settings"))


@admin_bp.route("/users/new", methods=["GET", "POST"])
@role_required("Admin")
def create_user():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "Viewer").strip()

        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
        elif role not in ROLES:
            flash("Invalid role selected.", "error")
        elif User.query.filter_by(email=email).first():
            flash("A user with that email already exists.", "error")
        else:
            user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                must_change_password=True,
                role=role,
            )
            db.session.add(user)
            db.session.commit()
            try:
                welcome_sent = send_welcome_email(user, password)
            except Exception as exc:
                flash(f"User account created, but welcome email failed: {exc}", "error")
                return redirect(url_for("admin.users"))

            if welcome_sent:
                flash("User account created and welcome email sent.", "success")
            else:
                flash("User account created. Welcome email was skipped because welcome email settings are incomplete.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/form.html", roles=ROLES)


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@role_required("Admin")
def update_role(user_id):
    user = User.query.get_or_404(user_id)
    role = request.form.get("role", "").strip()

    if role not in ROLES:
        flash("Invalid role selected.", "error")
    else:
        user.role = role
        db.session.commit()
        flash("User role updated.", "success")

    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle-access", methods=["POST"])
@role_required("Admin")
def toggle_access(user_id):
    user = User.query.get_or_404(user_id)
    admin_user = current_user()

    if user.id == admin_user.id and user.is_active:
        flash("You cannot remove your own access while signed in.", "error")
        return redirect(url_for("admin.users"))

    user.is_active = not user.is_active
    db.session.commit()
    flash("User access updated.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/send-reset", methods=["POST"])
@role_required("Admin")
def send_reset(user_id):
    user = User.query.get_or_404(user_id)
    reset_token = issue_password_reset_token(user)
    reset_url = build_password_reset_url(reset_token)

    try:
        sent = send_password_reset_email(user, reset_url)
    except Exception as exc:
        flash(f"Password reset email failed: {exc}", "error")
        return redirect(url_for("admin.users", token=reset_token.id))

    if sent:
        flash("Password reset email sent.", "success")
        return redirect(url_for("admin.users"))

    flash("Email settings are disabled or incomplete, so the reset link was generated for manual sharing.", "error")
    return redirect(url_for("admin.users", token=reset_token.id))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@role_required("Admin")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    admin_user = current_user()

    if user.id == admin_user.id:
        flash("Use the account page if you want to delete your own account.", "error")
        return redirect(url_for("admin.users"))

    allowed, reason = can_delete_user(user)
    if not allowed:
        flash(reason, "error")
        return redirect(url_for("admin.users"))

    PasswordResetToken.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash("User account deleted.", "success")
    return redirect(url_for("admin.users"))
