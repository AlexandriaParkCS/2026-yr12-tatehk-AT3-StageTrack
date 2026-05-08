from pathlib import Path
from uuid import uuid4

from flask import current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..auth.routes import login_required, role_required
from ..extensions import db
from ..models import Equipment
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


@equipment_bp.route("/<int:item_id>")
@login_required
def detail(item_id):
    item = Equipment.query.get_or_404(item_id)
    return render_template("equipment/detail.html", item=item)


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
            flash("Equipment added successfully.", "success")
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
            db.session.commit()
            flash("Equipment updated.", "success")
            return redirect(url_for("equipment.index"))

    return render_template("equipment/form.html", categories=CATEGORIES, statuses=STATUSES, item=item)


@equipment_bp.route("/<int:item_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(item_id):
    item = Equipment.query.get_or_404(item_id)
    if item.image_path:
        delete_image(item.image_path)
    db.session.delete(item)
    db.session.commit()
    flash("Equipment deleted.", "success")
    return redirect(url_for("equipment.index"))
