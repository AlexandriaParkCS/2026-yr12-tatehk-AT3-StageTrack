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
from ..models import PasswordResetToken, User
from ..site_service import get_site_settings
from . import admin_bp


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
        db.session.commit()
        flash("Site settings saved.", "success")
        return redirect(url_for("admin.site_settings"))

    return render_template("admin/site_settings.html", settings=settings)


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
