from datetime import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..email_service import build_password_reset_url, issue_password_reset_token, send_password_reset_email
from ..extensions import db
from ..models import EventCrewAssignment, PasswordResetToken, User
from . import auth_bp


ROLES = ["Admin", "Teacher", "Stage Manager", "Student Crew", "Viewer"]
MANAGER_ROLES = {"Admin", "Teacher", "Stage Manager"}


def can_delete_user_account(user):
    if user.role == "Admin" and User.query.filter_by(role="Admin", is_active=True).count() <= 1:
        return False, "You cannot delete the last active admin account."
    if user.tasks:
        return False, "Your account cannot be deleted while tasks are still assigned to you."
    if user.checkouts:
        return False, "Your account cannot be deleted while equipment checkout history is linked to it."
    if user.damage_reports:
        return False, "Your account cannot be deleted while damage reports are linked to it."
    if user.event_assignments:
        return False, "Your account cannot be deleted while event crew roles are linked to it."
    return True, None


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if user and not user.is_active:
        session.clear()
        return None
    return user


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*allowed_roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = current_user()
            if not user:
                return redirect(url_for("auth.login"))
            if user.role not in allowed_roles:
                flash("You do not have permission to access that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


@auth_bp.app_context_processor
def inject_user():
    first_user_pending = User.query.count() == 0
    return {
        "current_user": current_user(),
        "manager_roles": MANAGER_ROLES,
        "registration_open": first_user_pending,
    }


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    first_user_pending = User.query.count() == 0
    if not first_user_pending:
        flash("Open registration is disabled. An administrator can create accounts from the Admin page.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = "Admin"

        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
        elif role not in ROLES:
            flash("Invalid role selected.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        else:
            user = User(
                name=name,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please sign in.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
        elif not user.is_active:
            flash("This account has been disabled. Please contact an administrator.", "error")
        else:
            session.clear()
            session["user_id"] = user.id
            if user.must_change_password:
                flash("Please set a new password to finish activating your account.", "success")
                return redirect(url_for("auth.force_password_change"))
            flash(f"Welcome back, {user.name}.", "success")
            return redirect(url_for("dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()

        if user and user.is_active:
            reset_token = issue_password_reset_token(user)
            reset_url = build_password_reset_url(reset_token)

            try:
                send_password_reset_email(user, reset_url)
            except Exception:
                pass

        flash("If that email exists in StageTrack, a password reset link has been sent.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    user = current_user()

    if request.method == "POST":
        action = request.form.get("action", "profile")

        if action == "profile":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone_number = request.form.get("phone_number", "").strip()
            contact_details = request.form.get("contact_details", "").strip()

            existing_user = User.query.filter(User.email == email, User.id != user.id).first()

            if not name or not email:
                flash("Name and email are required.", "error")
            elif existing_user:
                flash("That email address is already being used by another account.", "error")
            else:
                user.name = name
                user.email = email
                user.phone_number = phone_number or None
                user.contact_details = contact_details or None
                db.session.commit()
                flash("Account details updated.", "success")
                return redirect(url_for("auth.account"))

        if action == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not check_password_hash(user.password_hash, current_password):
                flash("Your current password is incorrect.", "error")
            elif not new_password:
                flash("Please enter a new password.", "error")
            elif new_password != confirm_password:
                flash("New passwords do not match.", "error")
            else:
                user.password_hash = generate_password_hash(new_password)
                user.must_change_password = False
                db.session.commit()
                flash("Password updated successfully.", "success")
                return redirect(url_for("auth.account"))

        if action == "delete":
            password = request.form.get("delete_password", "")

            if not check_password_hash(user.password_hash, password):
                flash("Enter your current password to delete your account.", "error")
            else:
                allowed, reason = can_delete_user_account(user)
                if not allowed:
                    flash(reason, "error")
                else:
                    PasswordResetToken.query.filter_by(user_id=user.id).delete()
                    db.session.delete(user)
                    db.session.commit()
                    session.clear()
                    flash("Your account has been deleted.", "success")
                    return redirect(url_for("home"))

    return render_template("auth/account.html", user=user)


@auth_bp.route("/force-password-change", methods=["GET", "POST"])
@login_required
def force_password_change():
    user = current_user()

    if not user.must_change_password:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not new_password:
            flash("Please enter a new password.", "error")
        elif new_password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            user.password_hash = generate_password_hash(new_password)
            user.must_change_password = False
            db.session.commit()
            flash("Password updated successfully. Your account is ready to use.", "success")
            return redirect(url_for("dashboard"))

    return render_template("auth/force_password_change.html")


@auth_bp.route("/accept-event-invite/<token>", methods=["GET", "POST"])
def accept_event_invite(token):
    reset_token = PasswordResetToken.query.filter_by(token=token).first_or_404()
    now = datetime.utcnow()

    if reset_token.used_at or reset_token.expires_at < now:
        flash("That event invitation link is no longer valid.", "error")
        return redirect(url_for("auth.login"))

    user = reset_token.user

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name:
            flash("Please enter your name.", "error")
        elif not password:
            flash("Please enter a password.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            user.name = name
            user.password_hash = generate_password_hash(password)
            user.must_change_password = False
            reset_token.used_at = now
            EventCrewAssignment.query.filter_by(crew_email=user.email).update({"user_id": user.id})
            db.session.commit()
            flash("Your StageTrack account is ready. Please sign in to view your event.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/accept_event_invite.html", invited_user=user)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    reset_token = PasswordResetToken.query.filter_by(token=token).first_or_404()
    now = datetime.utcnow()

    if reset_token.used_at or reset_token.expires_at < now:
        flash("That password reset link is no longer valid.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password:
            flash("Please enter a new password.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            reset_token.user.password_hash = generate_password_hash(password)
            reset_token.user.must_change_password = False
            reset_token.used_at = now
            db.session.commit()
            flash("Password updated. You can sign in now.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", reset_token=reset_token)
