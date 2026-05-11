from datetime import datetime
from pathlib import Path
from uuid import uuid4

import qrcode
from flask import current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..auth.routes import current_user, login_required, role_required
from ..extensions import db
from ..models import Equipment, EquipmentCheckout, Event, User
from . import equipment_bp


CATEGORIES = ["Audio", "Lighting", "Cables", "Instruments", "Props", "AV Equipment", "Staging Gear"]
STATUSES = ["Available", "In Use", "Missing", "Damaged", "Under Repair"]
UPLOAD_SUBFOLDER = "equipment"


def allowed_image(filename):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def equipment_upload_dir():
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"]) / UPLOAD_SUBFOLDER
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def qr_code_dir():
    qr_dir = Path(current_app.config["QR_FOLDER"])
    qr_dir.mkdir(parents=True, exist_ok=True)
    return qr_dir


def public_stage_url():
    configured_base = (current_app.config.get("BASE_URL") or "").strip()
    return configured_base.rstrip("/") if configured_base else "https://stagetrack.xyz"


def build_qr_target_url(item_id):
    return f"{public_stage_url()}{url_for('equipment.qr_entry', item_id=item_id)}"


def generate_qr_code(item):
    if not item.id:
        return

    filename = f"equipment-{item.id}.png"
    destination = qr_code_dir() / filename
    qr_image = qrcode.make(build_qr_target_url(item.id))
    qr_image.save(destination)
    item.qr_code = filename


def delete_qr_code(qr_code_path):
    if not qr_code_path:
        return

    target = qr_code_dir() / qr_code_path
    if target.exists() and target.is_file():
        target.unlink()


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not allowed_image(file_storage.filename):
        return False

    filename = secure_filename(file_storage.filename)
    extension = filename.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{extension}"
    destination = equipment_upload_dir() / stored_name
    file_storage.save(destination)
    return f"{UPLOAD_SUBFOLDER}/{stored_name}"


def delete_image(image_path):
    if not image_path:
        return

    target = Path(current_app.config["UPLOAD_FOLDER"]) / image_path
    if target.exists() and target.is_file():
        target.unlink()


def active_checkout_for_item(item_id):
    return EquipmentCheckout.query.filter_by(equipment_id=item_id, return_time=None).order_by(EquipmentCheckout.checkout_time.desc()).first()


@equipment_bp.route("/")
@login_required
def index():
    query = Equipment.query
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Equipment.name.ilike(pattern),
                Equipment.serial_number.ilike(pattern),
                Equipment.location.ilike(pattern),
                Equipment.description.ilike(pattern),
            )
        )
    if category:
        query = query.filter_by(category=category)

    equipment_items = query.order_by(Equipment.name.asc()).all()
    return render_template(
        "equipment/index.html",
        equipment_items=equipment_items,
        categories=CATEGORIES,
        current_search=search,
        current_category=category,
    )


@equipment_bp.route("/scanner")
@login_required
def scanner():
    return render_template("equipment/scanner.html")


@equipment_bp.route("/qr/<int:item_id>")
def qr_entry(item_id):
    Equipment.query.get_or_404(item_id)
    if not current_user():
        return redirect(url_for("home"))
    return redirect(url_for("equipment.detail", item_id=item_id, scanner=1))


@equipment_bp.route("/<int:item_id>")
@login_required
def detail(item_id):
    item = Equipment.query.get_or_404(item_id)
    if not item.qr_code:
        generate_qr_code(item)
        db.session.commit()

    active_checkout = active_checkout_for_item(item.id)
    checkout_history = EquipmentCheckout.query.filter_by(equipment_id=item.id).order_by(EquipmentCheckout.checkout_time.desc()).limit(8).all()
    crew_users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    events = Event.query.order_by(Event.event_date.asc()).all()
    return render_template(
        "equipment/detail.html",
        item=item,
        active_checkout=active_checkout,
        checkout_history=checkout_history,
        crew_users=crew_users,
        events=events,
        public_qr_target=build_qr_target_url(item.id),
        scanned=request.args.get("scanner") == "1",
    )


@equipment_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    if request.method == "POST":
        serial_number = request.form.get("serial_number", "").strip() or None
        item = Equipment(
            name=request.form.get("name", "").strip(),
            category=request.form.get("category", "").strip(),
            description=request.form.get("description", "").strip(),
            serial_number=serial_number,
            condition=request.form.get("condition", "").strip() or "Good",
            location=request.form.get("location", "").strip(),
            status=request.form.get("status", "Available").strip(),
        )
        uploaded_image = save_image(request.files.get("image"))

        if not item.name or item.category not in CATEGORIES or item.status not in STATUSES:
            flash("Please complete the required equipment fields.", "error")
        elif serial_number and Equipment.query.filter_by(serial_number=serial_number).first():
            flash("That serial number is already assigned to another equipment item.", "error")
        elif uploaded_image is False:
            flash("Please upload a valid image file: png, jpg, jpeg, gif, or webp.", "error")
        else:
            if uploaded_image:
                item.image_path = uploaded_image
            db.session.add(item)
            db.session.commit()
            generate_qr_code(item)
            db.session.commit()
            flash("Equipment added successfully and QR code generated.", "success")
            return redirect(url_for("equipment.index"))

    return render_template("equipment/form.html", categories=CATEGORIES, statuses=STATUSES, item=None)


@equipment_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(item_id):
    item = Equipment.query.get_or_404(item_id)

    if request.method == "POST":
        serial_number = request.form.get("serial_number", "").strip() or None
        item.name = request.form.get("name", "").strip()
        item.category = request.form.get("category", "").strip()
        item.description = request.form.get("description", "").strip()
        item.serial_number = serial_number
        item.condition = request.form.get("condition", "").strip() or "Good"
        item.location = request.form.get("location", "").strip()
        item.status = request.form.get("status", "Available").strip()
        replace_image = save_image(request.files.get("image"))
        remove_image = request.form.get("remove_image") == "on"
        existing_serial = None
        if serial_number:
            existing_serial = Equipment.query.filter(Equipment.serial_number == serial_number, Equipment.id != item.id).first()

        if not item.name or item.category not in CATEGORIES or item.status not in STATUSES:
            flash("Please complete the required equipment fields.", "error")
        elif existing_serial:
            flash("That serial number is already assigned to another equipment item.", "error")
        elif replace_image is False:
            flash("Please upload a valid image file: png, jpg, jpeg, gif, or webp.", "error")
        else:
            if remove_image and item.image_path:
                delete_image(item.image_path)
                item.image_path = None
            if replace_image:
                if item.image_path:
                    delete_image(item.image_path)
                item.image_path = replace_image
            generate_qr_code(item)
            db.session.commit()
            flash("Equipment updated and QR code refreshed.", "success")
            return redirect(url_for("equipment.index"))

    return render_template("equipment/form.html", categories=CATEGORIES, statuses=STATUSES, item=item)


@equipment_bp.route("/<int:item_id>/checkout", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def checkout(item_id):
    item = Equipment.query.get_or_404(item_id)
    active_checkout = active_checkout_for_item(item.id)
    user_id = request.form.get("user_id", type=int)
    event_id = request.form.get("event_id", type=int)
    assignee = db.session.get(User, user_id) if user_id else None
    event = db.session.get(Event, event_id) if event_id else None

    if active_checkout:
        flash("This item is already checked out.", "error")
    elif item.status != "Available":
        flash("Only equipment marked as Available can be checked out from this screen.", "error")
    elif not assignee or not assignee.is_active:
        flash("Select an active crew member or staff member.", "error")
    elif event_id and not event:
        flash("Select a valid event or leave the event field blank.", "error")
    else:
        checkout_record = EquipmentCheckout(
            equipment_id=item.id,
            user_id=assignee.id,
            event_id=event.id if event else None,
            status="Checked Out",
        )
        item.status = "In Use"
        db.session.add(checkout_record)
        db.session.commit()
        flash(f"{item.name} checked out to {assignee.name}.", "success")

    return redirect(url_for("equipment.detail", item_id=item.id, scanner=1))


@equipment_bp.route("/<int:item_id>/checkin", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def checkin(item_id):
    item = Equipment.query.get_or_404(item_id)
    active_checkout = active_checkout_for_item(item.id)

    if not active_checkout:
        flash("This item is not currently checked out.", "error")
    else:
        active_checkout.return_time = datetime.utcnow()
        active_checkout.status = "Returned"
        item.status = "Available"
        db.session.commit()
        flash(f"{item.name} has been checked back in.", "success")

    return redirect(url_for("equipment.detail", item_id=item.id, scanner=1))


@equipment_bp.route("/<int:item_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(item_id):
    item = Equipment.query.get_or_404(item_id)
    if item.image_path:
        delete_image(item.image_path)
    if item.qr_code:
        delete_qr_code(item.qr_code)
    db.session.delete(item)
    db.session.commit()
    flash("Equipment deleted.", "success")
    return redirect(url_for("equipment.index"))
