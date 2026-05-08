import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from secrets import token_urlsafe

from flask import current_app, url_for

from .extensions import db
from .models import EmailSettings, PasswordResetToken


def get_email_settings():
    settings = EmailSettings.query.order_by(EmailSettings.id.asc()).first()
    if not settings:
        settings = EmailSettings()
        db.session.add(settings)
        db.session.commit()
    return settings


def get_sender_email(settings, email_type):
    if email_type == "password_reset":
        return settings.smtp_from_reset_email or settings.smtp_from_email
    if email_type == "welcome":
        return settings.smtp_from_welcome_email or settings.smtp_from_email
    return settings.smtp_from_email


def email_settings_ready(settings, email_type="general"):
    sender_email = get_sender_email(settings, email_type)
    return bool(settings.smtp_enabled and settings.smtp_host and sender_email)


def deliver_email(settings, recipient_email, subject, body, email_type="general"):
    sender_email = get_sender_email(settings, email_type)
    if not email_settings_ready(settings, email_type):
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password or "")
        server.send_message(message)

    return True


def send_password_reset_email(user, reset_url):
    settings = get_email_settings()
    body = (
        "A StageTrack password reset was requested for your account.\n\n"
        f"Use this link to choose a new password:\n{reset_url}\n\n"
        f"This link expires in {current_app.config['RESET_TOKEN_HOURS']} hours."
    )
    return deliver_email(settings, user.email, "StageTrack Password Reset", body, email_type="password_reset")


def send_welcome_email(user, temporary_password):
    settings = get_email_settings()
    body = (
        f"Welcome to StageTrack, {user.name}.\n\n"
        "An administrator has created your account.\n\n"
        f"Sign-in email: {user.email}\n"
        f"Temporary password: {temporary_password}\n"
        f"Role: {user.role}\n\n"
        "Please sign in and change your password as soon as possible."
    )
    return deliver_email(settings, user.email, "Welcome to StageTrack", body, email_type="welcome")


def issue_password_reset_token(user):
    PasswordResetToken.query.filter_by(user_id=user.id, used_at=None).update({"used_at": datetime.utcnow()})

    reset_token = PasswordResetToken(
        user_id=user.id,
        token=token_urlsafe(32),
        expires_at=datetime.utcnow() + timedelta(hours=current_app.config["RESET_TOKEN_HOURS"]),
    )
    db.session.add(reset_token)
    db.session.commit()
    return reset_token


def build_password_reset_url(reset_token):
    return url_for("auth.reset_password", token=reset_token.token, _external=True)
