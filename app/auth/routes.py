from datetime import datetime
from functools import wraps

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from ..models import PasswordResetToken, User
from . import auth_bp


ROLES = ["Admin", "Teacher", "Stage Manager", "Student Crew", "Viewer"]
MANAGER_ROLES = {"Admin", "Teacher", "Stage Manager"}


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
            flash(f"Welcome back, {user.name}.", "success")
            return redirect(url_for("dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


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
            reset_token.used_at = now
            db.session.commit()
            flash("Password updated. You can sign in now.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", reset_token=reset_token)
