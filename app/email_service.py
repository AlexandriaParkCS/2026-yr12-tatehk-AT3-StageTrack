import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
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


def get_logo_path():
    return Path(current_app.static_folder) / "images" / "stagetrack-logo.png"


def build_email_html(preheader, heading, intro, body_html, cta_label=None, cta_url=None, footer_note=None, logo_src="cid:stagetrack-logo"):
    cta_block = ""
    if cta_label and cta_url:
        cta_block = f"""
            <tr>
                <td style="padding: 0 32px 28px;">
                    <a href="{escape(cta_url, quote=True)}" style="
                        display: inline-block;
                        padding: 14px 22px;
                        border-radius: 999px;
                        background: linear-gradient(180deg, #ffd33d 0%, #ffb800 100%);
                        color: #16120a;
                        font-family: Arial, Helvetica, sans-serif;
                        font-size: 15px;
                        font-weight: 700;
                        text-decoration: none;
                    ">{escape(cta_label)}</a>
                </td>
            </tr>
        """

    footer_copy = footer_note or "This email was sent by StageTrack backstage management."

    return f"""\
<!doctype html>
<html lang="en">
<body style="margin:0; padding:0; background:#060708;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">
        {escape(preheader)}
    </div>
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#060708; margin:0; padding:32px 16px;">
        <tr>
            <td align="center">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:680px; background:#111419; border:1px solid rgba(255,255,255,0.08); border-radius:28px; overflow:hidden;">
                    <tr>
                        <td style="padding:28px 32px 20px; background:
                            radial-gradient(circle at top left, rgba(255,211,61,0.24), transparent 28%),
                            linear-gradient(180deg, #14181d 0%, #101317 100%);
                            border-bottom:1px solid rgba(255,255,255,0.06);">
                            <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                                <tr>
                                    <td style="vertical-align:middle;">
                                        <img src="{escape(logo_src, quote=True)}" alt="StageTrack logo" width="78" style="display:block; width:78px; height:auto; border-radius:16px;">
                                    </td>
                                    <td style="padding-left:16px; vertical-align:middle;">
                                        <div style="font-family: Arial, Helvetica, sans-serif; font-size:13px; letter-spacing:0.18em; text-transform:uppercase; color:#ffd33d; font-weight:700;">StageTrack</div>
                                        <div style="font-family: Arial, Helvetica, sans-serif; font-size:30px; line-height:1; color:#f4f5f7; font-weight:800; margin-top:6px;">{escape(heading)}</div>
                                        <div style="font-family: Arial, Helvetica, sans-serif; font-size:14px; color:#a6adb8; margin-top:8px;">Backstage management made easy</div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:28px 32px 10px; font-family: Arial, Helvetica, sans-serif; font-size:16px; line-height:1.7; color:#d7dbe1;">
                            <p style="margin:0 0 16px; color:#f4f5f7;">{escape(intro)}</p>
                            {body_html}
                        </td>
                    </tr>
                    {cta_block}
                    <tr>
                        <td style="padding:0 32px 32px;">
                            <div style="padding:16px 18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06); font-family: Arial, Helvetica, sans-serif; font-size:13px; line-height:1.6; color:#99a1ad;">
                                {escape(footer_copy)}
                            </div>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def deliver_email(settings, recipient_email, subject, body, email_type="general", html_body=None):
    sender_email = get_sender_email(settings, email_type)
    if not email_settings_ready(settings, email_type):
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient_email
    message.set_content(body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
        logo_path = get_logo_path()
        if logo_path.exists():
            with logo_path.open("rb") as logo_file:
                logo_bytes = logo_file.read()
            for part in message.iter_parts():
                if part.get_content_type() == "text/html":
                    part.add_related(logo_bytes, maintype="image", subtype="png", cid="<stagetrack-logo>")
                    break

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
    html_body = build_email_html(
        preheader="Use your secure StageTrack password reset link.",
        heading="Password Reset",
        intro="A password reset was requested for your StageTrack account.",
        body_html=f"""
            <p style="margin:0 0 16px;">Use the button below to choose a new password. This link expires in <strong style="color:#ffd33d;">{current_app.config['RESET_TOKEN_HOURS']} hours</strong>.</p>
            <div style="padding:16px 18px; border-radius:18px; background:rgba(255,211,61,0.08); border:1px solid rgba(255,211,61,0.18); color:#f4f5f7;">
                <strong style="display:block; margin-bottom:6px; color:#ffd33d;">Account</strong>
                <span>{escape(user.email)}</span>
            </div>
        """,
        cta_label="Reset password",
        cta_url=reset_url,
        footer_note="If you did not request this change, you can safely ignore this email."
    )
    return deliver_email(
        settings,
        user.email,
        "StageTrack Password Reset",
        body,
        email_type="password_reset",
        html_body=html_body,
    )


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
    login_url = current_app.config.get("BASE_URL", "").rstrip("/")
    if login_url:
        login_url = f"{login_url}/auth/login"
    else:
        login_url = "#"
    html_body = build_email_html(
        preheader="Your StageTrack account is ready.",
        heading="Welcome to StageTrack",
        intro=f"Hi {escape(user.name)}, your StageTrack account has been created and is ready to use.",
        body_html=f"""
            <p style="margin:0 0 16px;">Use the details below to sign in for the first time.</p>
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Email</strong><br>{escape(user.email)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Temporary password</strong><br>{escape(temporary_password)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Role</strong><br>{escape(user.role)}</p>
            </div>
        """,
        cta_label="Open StageTrack",
        cta_url=login_url,
        footer_note="Please sign in and change your password as soon as possible."
    )
    return deliver_email(
        settings,
        user.email,
        "Welcome to StageTrack",
        body,
        email_type="welcome",
        html_body=html_body,
    )


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
