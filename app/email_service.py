import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from html import escape
from pathlib import Path
from secrets import token_urlsafe

from flask import current_app, url_for

from .extensions import db
from .models import EmailSettings, PasswordResetToken
from .system_settings_service import get_system_settings, subject_template


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
    if email_type == "equipment":
        return settings.smtp_from_equipment_email or settings.smtp_from_email
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
    system_settings = get_system_settings()
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
        system_settings.password_reset_email_subject,
        body,
        email_type="password_reset",
        html_body=html_body,
    )


def send_welcome_email(user, temporary_password):
    settings = get_email_settings()
    system_settings = get_system_settings()
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
        system_settings.welcome_email_subject,
        body,
        email_type="welcome",
        html_body=html_body,
    )


def build_login_url():
    base_url = current_app.config.get("BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}/auth/login"
    return url_for("auth.login", _external=True)


def build_event_invite_url(reset_token):
    return url_for("auth.accept_event_invite", token=reset_token.token, _external=True)


def build_equipment_url(equipment):
    return url_for("equipment.detail", item_id=equipment.id, _external=True)


def build_task_url(task):
    return url_for("events.detail", event_id=task.event.id, _external=True)


def send_event_assignment_email(user, event, crew_role):
    settings = get_email_settings()
    login_url = build_login_url()
    event_url = url_for("events.detail", event_id=event.id, _external=True)
    body = (
        f"Hi {user.name},\n\n"
        f"You have been added to the StageTrack event '{event.name}'.\n"
        f"Your event role: {crew_role}\n"
        f"Venue: {event.venue}\n"
        f"Event date: {event.event_date.strftime('%d %b %Y %I:%M %p')}\n\n"
        f"Sign in here: {login_url}\n"
        f"Event link: {event_url}"
    )
    html_body = build_email_html(
        preheader="You have been linked to a StageTrack event.",
        heading="New Event Assignment",
        intro=f"Hi {escape(user.name)}, you have been linked to a StageTrack event.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(event.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Your role</strong><br>{escape(crew_role)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Venue</strong><br>{escape(event.venue)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Date</strong><br>{escape(event.event_date.strftime('%d %b %Y %I:%M %p'))}</p>
            </div>
        """,
        cta_label="Sign in to view event",
        cta_url=event_url,
        footer_note="Sign in to StageTrack to view the event and your linked crew role."
    )
    return deliver_email(
        settings,
        user.email,
        f"StageTrack event assignment: {event.name}",
        body,
        email_type="general",
        html_body=html_body,
    )


def send_task_assignment_email(task):
    settings = get_email_settings()
    task_url = build_task_url(task)
    body = (
        f"Hi {task.assignee.name},\n\n"
        f"You have been assigned a new StageTrack task for '{task.event.name}'.\n"
        f"Task: {task.title}\n"
        f"Status: {task.status}\n"
        f"Due: {task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set'}\n\n"
        f"Open the event here:\n{task_url}"
    )
    html_body = build_email_html(
        preheader="A new StageTrack task has been assigned to you.",
        heading="New Task Assigned",
        intro=f"Hi {escape(task.assignee.name)}, you have a new StageTrack task.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(task.event.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Task</strong><br>{escape(task.title)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Status</strong><br>{escape(task.status)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Due</strong><br>{escape(task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set')}</p>
            </div>
        """,
        cta_label="Open event",
        cta_url=task_url,
        footer_note="You are receiving this because a StageTrack manager assigned work to your account."
    )
    return deliver_email(settings, task.assignee.email, f"StageTrack task assigned: {task.title}", body, html_body=html_body)


def send_task_update_email(task):
    settings = get_email_settings()
    task_url = build_task_url(task)
    body = (
        f"Hi {task.assignee.name},\n\n"
        f"Your StageTrack task has been updated for '{task.event.name}'.\n"
        f"Task: {task.title}\n"
        f"Status: {task.status}\n"
        f"Due: {task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set'}\n\n"
        f"Open the event here:\n{task_url}"
    )
    html_body = build_email_html(
        preheader="A StageTrack task assigned to you has been updated.",
        heading="Task Updated",
        intro=f"Hi {escape(task.assignee.name)}, one of your StageTrack tasks has been updated.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(task.event.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Task</strong><br>{escape(task.title)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Status</strong><br>{escape(task.status)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Due</strong><br>{escape(task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set')}</p>
            </div>
        """,
        cta_label="Open event",
        cta_url=task_url,
        footer_note="This message was sent because a StageTrack manager updated your task."
    )
    return deliver_email(settings, task.assignee.email, f"StageTrack task updated: {task.title}", body, html_body=html_body)


def send_task_overdue_email(task):
    settings = get_email_settings()
    task_url = build_task_url(task)
    body = (
        f"Hi {task.assignee.name},\n\n"
        f"Your StageTrack task is now overdue for '{task.event.name}'.\n"
        f"Task: {task.title}\n"
        f"Due: {task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set'}\n\n"
        f"Open the event here:\n{task_url}"
    )
    html_body = build_email_html(
        preheader="A StageTrack task assigned to you is overdue.",
        heading="Task Overdue",
        intro=f"Hi {escape(task.assignee.name)}, StageTrack has marked one of your tasks as overdue.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,125,125,0.08); border:1px solid rgba(255,125,125,0.16);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(task.event.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Task</strong><br>{escape(task.title)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Due</strong><br>{escape(task.due_time.strftime('%d %b %Y %I:%M %p') if task.due_time else 'No due time set')}</p>
            </div>
        """,
        cta_label="Open event",
        cta_url=task_url,
        footer_note="Please update the task status or speak with your event lead if the schedule needs to change."
    )
    return deliver_email(settings, task.assignee.email, f"StageTrack task overdue: {task.title}", body, html_body=html_body)


def send_event_invite_email(user, event, crew_role, invite_url):
    settings = get_email_settings()
    body = (
        f"You have been added to the StageTrack event '{event.name}'.\n\n"
        f"Your event role: {crew_role}\n"
        f"Venue: {event.venue}\n"
        f"Event date: {event.event_date.strftime('%d %b %Y %I:%M %p')}\n\n"
        "Finish setting up your StageTrack account with this secure link:\n"
        f"{invite_url}"
    )
    html_body = build_email_html(
        preheader="Finish setting up your StageTrack account.",
        heading="You Have Been Added to an Event",
        intro="A StageTrack event creator has linked you to an upcoming event.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(event.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Your role</strong><br>{escape(crew_role)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Venue</strong><br>{escape(event.venue)}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Date</strong><br>{escape(event.event_date.strftime('%d %b %Y %I:%M %p'))}</p>
            </div>
            <p style="margin:16px 0 0;">Use the button below to finish creating your StageTrack access and view the event.</p>
        """,
        cta_label="Set up account",
        cta_url=invite_url,
        footer_note="This secure setup link will let you finish your account and open StageTrack."
    )
    return deliver_email(
        settings,
        user.email,
        f"StageTrack invite for {event.name}",
        body,
        email_type="welcome",
        html_body=html_body,
    )


def send_equipment_checkout_email(checkout):
    settings = get_email_settings()
    system_settings = get_system_settings()
    if not settings.notify_equipment_checkout:
        return False

    user = checkout.user
    equipment = checkout.equipment
    equipment_url = build_equipment_url(equipment)
    body = (
        f"Hi {user.name},\n\n"
        f"{equipment.name} has been checked out to you in StageTrack.\n"
        f"Status: {equipment.status}\n"
        f"Location: {equipment.location or 'Not set'}\n"
        f"Event: {checkout.event.name if checkout.event else 'No event linked'}\n"
        f"Due: {checkout.due_at.strftime('%d %b %Y %I:%M %p') if checkout.due_at else 'No due date set'}\n\n"
        f"View the equipment here:\n{equipment_url}"
    )
    html_body = build_email_html(
        preheader="Equipment has been checked out to you.",
        heading="Equipment Checked Out",
        intro=f"Hi {escape(user.name)}, this equipment has been checked out to you in StageTrack.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Equipment</strong><br>{escape(equipment.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(checkout.event.name if checkout.event else 'No event linked')}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Location</strong><br>{escape(equipment.location or 'Not set')}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Due</strong><br>{escape(checkout.due_at.strftime('%d %b %Y %I:%M %p') if checkout.due_at else 'No due date set')}</p>
            </div>
        """,
        cta_label="Open equipment",
        cta_url=equipment_url,
        footer_note="You are receiving this because equipment was checked out under your StageTrack account."
    )
    return deliver_email(settings, user.email, subject_template(system_settings.equipment_checkout_email_subject, equipment_name=equipment.name), body, email_type="equipment", html_body=html_body)


def send_equipment_overdue_email(checkout):
    settings = get_email_settings()
    system_settings = get_system_settings()
    if not settings.notify_equipment_overdue:
        return False

    user = checkout.user
    equipment = checkout.equipment
    equipment_url = build_equipment_url(equipment)
    body = (
        f"Hi {user.name},\n\n"
        f"{equipment.name} is now overdue in StageTrack.\n"
        f"Event: {checkout.event.name if checkout.event else 'No event linked'}\n"
        f"Due: {checkout.due_at.strftime('%d %b %Y %I:%M %p') if checkout.due_at else 'No due date set'}\n\n"
        f"View the equipment here:\n{equipment_url}"
    )
    html_body = build_email_html(
        preheader="Equipment under your name is overdue.",
        heading="Equipment Overdue",
        intro=f"Hi {escape(user.name)}, StageTrack has marked this equipment as overdue.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,125,125,0.08); border:1px solid rgba(255,125,125,0.16);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Equipment</strong><br>{escape(equipment.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(checkout.event.name if checkout.event else 'No event linked')}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Due</strong><br>{escape(checkout.due_at.strftime('%d %b %Y %I:%M %p') if checkout.due_at else 'No due date set')}</p>
            </div>
        """,
        cta_label="Open equipment",
        cta_url=equipment_url,
        footer_note="Please arrange a return or update the equipment record if the due date needs to change."
    )
    return deliver_email(settings, user.email, subject_template(system_settings.equipment_overdue_email_subject, equipment_name=equipment.name), body, email_type="equipment", html_body=html_body)


def send_equipment_return_email(checkout):
    settings = get_email_settings()
    system_settings = get_system_settings()
    if not settings.notify_equipment_return:
        return False

    user = checkout.user
    equipment = checkout.equipment
    equipment_url = build_equipment_url(equipment)
    body = (
        f"Hi {user.name},\n\n"
        f"{equipment.name} has been checked back in within StageTrack.\n"
        f"Event: {checkout.event.name if checkout.event else 'No event linked'}\n"
        f"Returned: {checkout.return_time.strftime('%d %b %Y %I:%M %p') if checkout.return_time else 'Just now'}\n\n"
        f"View the equipment here:\n{equipment_url}"
    )
    html_body = build_email_html(
        preheader="Equipment has been returned in StageTrack.",
        heading="Equipment Returned",
        intro=f"Hi {escape(user.name)}, this equipment has been checked back in.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Equipment</strong><br>{escape(equipment.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Event</strong><br>{escape(checkout.event.name if checkout.event else 'No event linked')}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Returned</strong><br>{escape(checkout.return_time.strftime('%d %b %Y %I:%M %p') if checkout.return_time else 'Just now')}</p>
            </div>
        """,
        cta_label="Open equipment",
        cta_url=equipment_url,
        footer_note="This message confirms that the equipment has been returned and the record has been updated."
    )
    return deliver_email(settings, user.email, subject_template(system_settings.equipment_return_email_subject, equipment_name=equipment.name), body, email_type="equipment", html_body=html_body)


def send_maintenance_request_email(recipient_email, report, reporter):
    settings = get_email_settings()
    system_settings = get_system_settings()
    equipment = report.equipment
    equipment_url = build_equipment_url(equipment)
    body = (
        "A new StageTrack maintenance request has been submitted.\n\n"
        f"Equipment: {equipment.name}\n"
        f"Reported by: {reporter.name} ({reporter.email})\n"
        f"Location: {equipment.location or 'Not set'}\n"
        f"Status: {equipment.status}\n"
        f"Problem: {report.description}\n\n"
        f"View the equipment here:\n{equipment_url}"
    )
    html_body = build_email_html(
        preheader="A new maintenance request was submitted in StageTrack.",
        heading="Maintenance Request",
        intro="A user has submitted a new equipment maintenance request.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Equipment</strong><br>{escape(equipment.name)}</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Reported by</strong><br>{escape(reporter.name)} ({escape(reporter.email)})</p>
                <p style="margin:0 0 8px;"><strong style="color:#ffd33d;">Location</strong><br>{escape(equipment.location or 'Not set')}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Issue</strong><br>{escape(report.description)}</p>
            </div>
        """,
        cta_label="Open equipment",
        cta_url=equipment_url,
        footer_note="This request was submitted through the StageTrack equipment maintenance workflow."
    )
    return deliver_email(
        settings,
        recipient_email,
        subject_template(system_settings.maintenance_email_subject, equipment_name=equipment.name),
        body,
        email_type="equipment",
        html_body=html_body,
    )


def send_enquiry_email(recipient_email, enquiry_data):
    settings = get_email_settings()
    system_settings = get_system_settings()
    body = (
        "A new StageTrack website enquiry has been submitted.\n\n"
        f"Name: {enquiry_data['name']}\n"
        f"Email: {enquiry_data['email']}\n"
        f"Contact: {enquiry_data['contact']}\n"
        f"Use case: {enquiry_data['use_case']}\n"
        f"Message: {enquiry_data['message'] or 'No extra message provided.'}"
    )
    html_body = build_email_html(
        preheader="A new StageTrack enquiry was submitted.",
        heading="New Enquiry",
        intro="A visitor has sent a new enquiry from the StageTrack public website.",
        body_html=f"""
            <div style="padding:18px; border-radius:18px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06);">
                <p style="margin:0 0 10px;"><strong style="color:#ffd33d;">Name</strong><br>{escape(enquiry_data['name'])}</p>
                <p style="margin:0 0 10px;"><strong style="color:#ffd33d;">Email</strong><br>{escape(enquiry_data['email'])}</p>
                <p style="margin:0 0 10px;"><strong style="color:#ffd33d;">Contact</strong><br>{escape(enquiry_data['contact'])}</p>
                <p style="margin:0 0 10px;"><strong style="color:#ffd33d;">Use case</strong><br>{escape(enquiry_data['use_case'])}</p>
                <p style="margin:0;"><strong style="color:#ffd33d;">Message</strong><br>{escape(enquiry_data['message'] or 'No extra message provided.')}</p>
            </div>
        """,
        footer_note="This enquiry was sent from the public StageTrack website."
    )
    return deliver_email(
        settings,
        recipient_email,
        subject_template(system_settings.enquiry_email_subject, name=enquiry_data["name"]),
        body,
        email_type="general",
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
