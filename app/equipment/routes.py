from datetime import datetime
from pathlib import Path
from uuid import uuid4

import qrcode
from flask import current_app, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..auth.routes import current_user, login_required, role_required
from ..email_service import send_equipment_checkout_email, send_equipment_return_email, send_maintenance_request_email
from ..extensions import db
from ..pdf_service import build_kit_checkout_pdf, build_maintenance_pdf
from ..models import ConsumableAdjustment, ConsumableItem, DamageReport, Equipment, EquipmentCheckout, EquipmentKit, EquipmentKitItem, Event, StorageLocation, User
from ..system_settings_service import (
    alert_recipient_list,
    consumable_categories as configured_consumable_categories,
    equipment_categories as configured_equipment_categories,
    equipment_statuses as configured_equipment_statuses,
    get_system_settings,
    maintenance_statuses as configured_maintenance_statuses,
    role_meets_requirement,
)
from . import equipment_bp

UPLOAD_SUBFOLDER = "equipment"
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"


def allowed_image(filename):
    if not filename or "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]


def optional_form_value(name):
    raw_value = (request.form.get(name, "") or "").strip()
    if not raw_value or raw_value.lower() == "none":
        return None
    return raw_value


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


def kit_qr_filename(kit_id):
    return f"kit-{kit_id}.png"


def build_kit_qr_target_url(kit_id):
    return f"{public_stage_url()}{url_for('equipment.kit_qr_entry', kit_id=kit_id)}"


def generate_kit_qr_code(kit):
    if not kit.id:
        return None

    filename = kit_qr_filename(kit.id)
    destination = qr_code_dir() / filename
    qr_image = qrcode.make(build_kit_qr_target_url(kit.id))
    qr_image.save(destination)
    return filename


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


def display_status(item, now=None):
    current_time = now or datetime.now()
    active_checkout = active_checkout_for_item(item.id)
    if active_checkout and active_checkout.due_at and active_checkout.due_at < current_time:
        return "Overdue"
    return item.status


def can_delete_equipment(item):
    if active_checkout_for_item(item.id):
        return False, "This equipment is currently checked out and cannot be deleted."
    if item.checkouts:
        return False, "This equipment cannot be deleted while checkout history is linked to it."
    if item.damage_reports:
        return False, "This equipment cannot be deleted while damage reports are linked to it."
    return True, None


def parse_due_at(value):
    if not value:
        return None
    return datetime.strptime(value, DATETIME_LOCAL_FORMAT)


def filtered_equipment_query(include_removed=False, search="", category=""):
    query = Equipment.query
    if not include_removed:
        query = query.filter(Equipment.status != "Removed")

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
    return query


def active_storage_locations():
    return StorageLocation.query.filter_by(is_active=True).order_by(StorageLocation.name.asc(), StorageLocation.shelf.asc()).all()


def valid_location_labels(item=None):
    labels = {location.label for location in StorageLocation.query.order_by(StorageLocation.name.asc(), StorageLocation.shelf.asc()).all()}
    if item and item.location:
        labels.add(item.location)
    return labels


def active_checkout_records_for_kit(kit):
    item_ids = [link.equipment_id for link in kit.items]
    if not item_ids:
        return []
    return EquipmentCheckout.query.filter(
        EquipmentCheckout.equipment_id.in_(item_ids),
        EquipmentCheckout.return_time.is_(None),
    ).all()


def sync_kit_items(kit, equipment_ids):
    unique_ids = []
    for equipment_id in equipment_ids:
        if equipment_id and equipment_id not in unique_ids:
            unique_ids.append(equipment_id)

    kit.items.clear()
    for equipment_id in unique_ids:
        kit.items.append(EquipmentKitItem(equipment_id=equipment_id))


def low_stock_consumables():
    settings = get_system_settings()
    if settings.low_stock_alert_behavior == "below_only":
        return ConsumableItem.query.filter(ConsumableItem.quantity_on_hand < ConsumableItem.reorder_level).order_by(ConsumableItem.name.asc()).all()
    return ConsumableItem.query.filter(ConsumableItem.quantity_on_hand <= ConsumableItem.reorder_level).order_by(ConsumableItem.name.asc()).all()


@equipment_bp.route("/")
@login_required
def index():
    settings = get_system_settings()
    user = current_user()
    if user.role == "Student Crew" and not settings.student_crew_can_view_all_equipment:
        flash("Student Crew access to the equipment inventory is disabled in system settings.", "error")
        return redirect(url_for("dashboard"))
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()
    include_removed_arg = request.args.get("include_removed")
    include_removed = (include_removed_arg == "on") if include_removed_arg is not None else (not settings.auto_hide_removed_items)
    local_now = datetime.now()
    equipment_items = filtered_equipment_query(include_removed=include_removed, search=search, category=category).order_by(Equipment.name.asc()).all()

    if status_filter == "Overdue":
        equipment_items = [item for item in equipment_items if display_status(item, local_now) == "Overdue"]
    elif status_filter in configured_equipment_statuses():
        equipment_items = [item for item in equipment_items if item.status == status_filter]

    return render_template(
        "equipment/index.html",
        equipment_items=equipment_items,
        display_status=display_status,
        categories=configured_equipment_categories(),
        statuses=configured_equipment_statuses(),
        current_search=search,
        current_category=category,
        current_status=status_filter,
        include_removed=include_removed,
        now=local_now,
    )


@equipment_bp.route("/qr-labels")
@role_required("Admin", "Teacher", "Stage Manager")
def qr_labels():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    status_filter = request.args.get("status", "").strip()
    include_removed = request.args.get("include_removed") == "on"
    local_now = datetime.now()

    equipment_items = filtered_equipment_query(include_removed=include_removed, search=search, category=category).order_by(Equipment.name.asc()).all()
    if status_filter == "Overdue":
        equipment_items = [item for item in equipment_items if display_status(item, local_now) == "Overdue"]
    elif status_filter in configured_equipment_statuses():
        equipment_items = [item for item in equipment_items if item.status == status_filter]

    for item in equipment_items:
        if not item.qr_code:
            generate_qr_code(item)
    db.session.commit()

    return render_template("equipment/qr_labels.html", equipment_items=equipment_items, display_status=display_status, now=local_now)


@equipment_bp.route("/kits")
@role_required("Admin", "Teacher", "Stage Manager")
def kits():
    kit_list = EquipmentKit.query.order_by(EquipmentKit.name.asc()).all()
    return render_template("equipment/kits/index.html", kits=kit_list, active_checkout_for_item=active_checkout_for_item)


@equipment_bp.route("/kits/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create_kit():
    equipment_choices = Equipment.query.filter(Equipment.status != "Removed").order_by(Equipment.name.asc()).all()

    if request.method == "POST":
        kit = EquipmentKit(
            name=request.form.get("name", "").strip(),
            description=request.form.get("description", "").strip(),
        )
        selected_ids = request.form.getlist("equipment_ids")
        equipment_ids = [int(value) for value in selected_ids if value.isdigit()]

        if not kit.name:
            flash("Kit name is required.", "error")
        elif not equipment_ids:
            flash("Select at least one equipment item for the kit.", "error")
        else:
            db.session.add(kit)
            sync_kit_items(kit, equipment_ids)
            db.session.commit()
            flash("Equipment kit created.", "success")
            return redirect(url_for("equipment.kits"))

        return render_template("equipment/kits/form.html", kit=kit, equipment_choices=equipment_choices, selected_ids=equipment_ids)

    return render_template("equipment/kits/form.html", kit=None, equipment_choices=equipment_choices, selected_ids=[])


@equipment_bp.route("/kits/<int:kit_id>")
@role_required("Admin", "Teacher", "Stage Manager")
def kit_detail(kit_id):
    kit = EquipmentKit.query.get_or_404(kit_id)
    qr_filename = generate_kit_qr_code(kit)
    active_checkouts = active_checkout_records_for_kit(kit)
    active_checkout_map = {checkout.equipment_id: checkout for checkout in active_checkouts}
    crew_users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    events = Event.query.order_by(Event.event_date.asc()).all()
    return render_template(
        "equipment/kits/detail.html",
        kit=kit,
        active_checkout_map=active_checkout_map,
        crew_users=crew_users,
        events=events,
        now=datetime.now(),
        display_status=display_status,
        qr_filename=qr_filename,
        public_qr_target=build_kit_qr_target_url(kit.id),
        scanned=request.args.get("scanner") == "1",
    )


@equipment_bp.route("/kits/<int:kit_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit_kit(kit_id):
    kit = EquipmentKit.query.get_or_404(kit_id)
    equipment_choices = Equipment.query.filter(Equipment.status != "Removed").order_by(Equipment.name.asc()).all()

    if request.method == "POST":
        selected_ids = request.form.getlist("equipment_ids")
        equipment_ids = [int(value) for value in selected_ids if value.isdigit()]
        kit.name = request.form.get("name", "").strip()
        kit.description = request.form.get("description", "").strip()

        if not kit.name:
            flash("Kit name is required.", "error")
        elif not equipment_ids:
            flash("Select at least one equipment item for the kit.", "error")
        else:
            sync_kit_items(kit, equipment_ids)
            db.session.commit()
            flash("Equipment kit updated.", "success")
            return redirect(url_for("equipment.kit_detail", kit_id=kit.id))

        return render_template("equipment/kits/form.html", kit=kit, equipment_choices=equipment_choices, selected_ids=equipment_ids)

    selected_ids = [link.equipment_id for link in kit.items]
    return render_template("equipment/kits/form.html", kit=kit, equipment_choices=equipment_choices, selected_ids=selected_ids)


@equipment_bp.route("/kits/<int:kit_id>/checkout", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def checkout_kit(kit_id):
    kit = EquipmentKit.query.get_or_404(kit_id)
    settings = get_system_settings()
    if not role_meets_requirement(current_user().role, settings.checkout_permission_role):
        flash("Your account does not have permission to check out kits.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))
    user_id = request.form.get("user_id", type=int)
    event_id = request.form.get("event_id", type=int)
    assignee = db.session.get(User, user_id) if user_id else None
    event = db.session.get(Event, event_id) if event_id else None
    due_at_value = request.form.get("due_at", "").strip()

    try:
        due_at = parse_due_at(due_at_value)
    except ValueError:
        flash("Please enter a valid due date and time.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))

    if not assignee or not assignee.is_active:
        flash("Select an active crew member or staff member.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))
    if event_id and not event:
        flash("Select a valid event or leave the event field blank.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))
    if settings.due_dates_required and not due_at:
        flash("A due date is required for kit checkouts.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))
    if due_at and due_at <= datetime.now():
        flash("The due date must be in the future.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))

    blocking_items = []
    for link in kit.items:
        item = link.equipment
        if active_checkout_for_item(item.id) or item.status != "Available":
            blocking_items.append(item.name)

    if blocking_items:
        flash(f"This kit cannot be checked out until these items are ready: {', '.join(blocking_items[:4])}", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))

    for link in kit.items:
        item = link.equipment
        checkout_record = EquipmentCheckout(
            equipment_id=item.id,
            user_id=assignee.id,
            event_id=event.id if event else None,
            due_at=due_at,
            status="Checked Out",
        )
        item.status = "In Use"
        db.session.add(checkout_record)

    db.session.commit()
    flash(f"{kit.name} checked out to {assignee.name}.", "success")
    return redirect(url_for("equipment.kit_detail", kit_id=kit.id))


@equipment_bp.route("/kits/<int:kit_id>/checkin", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def checkin_kit(kit_id):
    kit = EquipmentKit.query.get_or_404(kit_id)
    active_checkouts = active_checkout_records_for_kit(kit)

    if not active_checkouts:
        flash("This kit does not have any items currently checked out.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))

    for checkout in active_checkouts:
        checkout.return_time = datetime.utcnow()
        checkout.status = "Returned"
        checkout.equipment.status = "Available"

    db.session.commit()
    flash(f"{kit.name} has been checked back in.", "success")
    return redirect(url_for("equipment.kit_detail", kit_id=kit.id))


@equipment_bp.route("/kits/<int:kit_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete_kit(kit_id):
    kit = EquipmentKit.query.get_or_404(kit_id)
    if active_checkout_records_for_kit(kit):
        flash("Check the kit back in before deleting it.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit.id))
    delete_qr_code(kit_qr_filename(kit.id))
    db.session.delete(kit)
    db.session.commit()
    flash("Equipment kit deleted.", "success")
    return redirect(url_for("equipment.kits"))


@equipment_bp.route("/kits/labels")
@role_required("Admin", "Teacher", "Stage Manager")
def kit_labels():
    if not role_meets_requirement(current_user().role, get_system_settings().pdf_export_permission_role):
        flash("You do not have permission to export kit labels.", "error")
        return redirect(url_for("equipment.kits"))
    kits = EquipmentKit.query.order_by(EquipmentKit.name.asc()).all()
    qr_filenames = {}
    for kit in kits:
        qr_filenames[kit.id] = generate_kit_qr_code(kit)
    return render_template("equipment/kits/labels.html", kits=kits, qr_filenames=qr_filenames)


@equipment_bp.route("/kits/<int:kit_id>/checkout-sheet")
@role_required("Admin", "Teacher", "Stage Manager")
def kit_checkout_sheet(kit_id):
    if not role_meets_requirement(current_user().role, get_system_settings().pdf_export_permission_role):
        flash("You do not have permission to view kit paperwork.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit_id))
    kit = EquipmentKit.query.get_or_404(kit_id)
    active_checkouts = active_checkout_records_for_kit(kit)
    active_checkout_map = {checkout.equipment_id: checkout for checkout in active_checkouts}
    qr_filename = generate_kit_qr_code(kit)
    return render_template(
        "equipment/kits/checkout_sheet.html",
        kit=kit,
        active_checkout_map=active_checkout_map,
        qr_filename=qr_filename,
        generated_at=datetime.now(),
    )


@equipment_bp.route("/kits/<int:kit_id>/checkout-sheet.pdf")
@role_required("Admin", "Teacher", "Stage Manager")
def kit_checkout_sheet_pdf(kit_id):
    if not role_meets_requirement(current_user().role, get_system_settings().pdf_export_permission_role):
        flash("You do not have permission to export kit paperwork.", "error")
        return redirect(url_for("equipment.kit_detail", kit_id=kit_id))
    kit = EquipmentKit.query.get_or_404(kit_id)
    active_checkouts = active_checkout_records_for_kit(kit)
    active_checkout_map = {checkout.equipment_id: checkout for checkout in active_checkouts}
    pdf_buffer, filename = build_kit_checkout_pdf(kit, active_checkout_map, datetime.now())
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@equipment_bp.route("/kits/qr/<int:kit_id>")
def kit_qr_entry(kit_id):
    EquipmentKit.query.get_or_404(kit_id)
    if not current_user():
        return redirect(url_for("home"))
    return redirect(url_for("equipment.kit_detail", kit_id=kit_id, scanner=1))


@equipment_bp.route("/consumables")
@role_required("Admin", "Teacher", "Stage Manager")
def consumables():
    if not role_meets_requirement(current_user().role, get_system_settings().consumable_manage_permission_role):
        flash("You do not have permission to manage consumables.", "error")
        return redirect(url_for("dashboard"))
    items = ConsumableItem.query.order_by(ConsumableItem.name.asc()).all()
    return render_template("equipment/consumables/index.html", consumables=items, low_stock=low_stock_consumables())


@equipment_bp.route("/consumables/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create_consumable():
    if not role_meets_requirement(current_user().role, get_system_settings().consumable_manage_permission_role):
        flash("You do not have permission to manage consumables.", "error")
        return redirect(url_for("dashboard"))
    categories = configured_consumable_categories()
    if request.method == "POST":
        item = ConsumableItem(
            name=request.form.get("name", "").strip(),
            category=request.form.get("category", "").strip(),
            location=request.form.get("location", "").strip() or None,
            unit_label=request.form.get("unit_label", "").strip() or "units",
            quantity_on_hand=request.form.get("quantity_on_hand", type=int) or 0,
            reorder_level=request.form.get("reorder_level", type=int) or 0,
            notes=request.form.get("notes", "").strip() or None,
        )

        if not item.name or item.category not in categories:
            flash("Consumable name and category are required.", "error")
        else:
            db.session.add(item)
            db.session.commit()
            flash("Consumable item created.", "success")
            return redirect(url_for("equipment.consumables"))

        return render_template("equipment/consumables/form.html", item=item, categories=categories)

    return render_template("equipment/consumables/form.html", item=None, categories=categories)


@equipment_bp.route("/consumables/<int:item_id>")
@role_required("Admin", "Teacher", "Stage Manager")
def consumable_detail(item_id):
    if not role_meets_requirement(current_user().role, get_system_settings().consumable_manage_permission_role):
        flash("You do not have permission to manage consumables.", "error")
        return redirect(url_for("dashboard"))
    item = ConsumableItem.query.get_or_404(item_id)
    return render_template("equipment/consumables/detail.html", item=item)


@equipment_bp.route("/consumables/<int:item_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit_consumable(item_id):
    if not role_meets_requirement(current_user().role, get_system_settings().consumable_manage_permission_role):
        flash("You do not have permission to manage consumables.", "error")
        return redirect(url_for("dashboard"))
    item = ConsumableItem.query.get_or_404(item_id)
    categories = configured_consumable_categories()

    if request.method == "POST":
        item.name = request.form.get("name", "").strip()
        item.category = request.form.get("category", "").strip()
        item.location = request.form.get("location", "").strip() or None
        item.unit_label = request.form.get("unit_label", "").strip() or "units"
        item.quantity_on_hand = request.form.get("quantity_on_hand", type=int) or 0
        item.reorder_level = request.form.get("reorder_level", type=int) or 0
        item.notes = request.form.get("notes", "").strip() or None

        if not item.name or item.category not in categories:
            flash("Consumable name and category are required.", "error")
        else:
            db.session.commit()
            flash("Consumable item updated.", "success")
            return redirect(url_for("equipment.consumable_detail", item_id=item.id))

    return render_template("equipment/consumables/form.html", item=item, categories=categories)


@equipment_bp.route("/consumables/<int:item_id>/adjust", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def adjust_consumable(item_id):
    settings = get_system_settings()
    if not role_meets_requirement(current_user().role, settings.consumable_manage_permission_role):
        flash("You do not have permission to manage consumables.", "error")
        return redirect(url_for("dashboard"))
    item = ConsumableItem.query.get_or_404(item_id)
    quantity_change = request.form.get("quantity_change", type=int)
    reason = request.form.get("reason", "").strip()

    if quantity_change is None or quantity_change == 0:
        flash("Enter a stock change above or below zero.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))
    if quantity_change < 0 and settings.negative_consumable_adjustments_manager_only and not role_meets_requirement(current_user().role, "Stage Manager"):
        flash("Only managers can apply negative manual stock adjustments.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))
    if item.quantity_on_hand + quantity_change < 0:
        flash("That adjustment would push stock below zero.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))

    adjustment = ConsumableAdjustment(
        consumable_id=item.id,
        user_id=current_user().id,
        quantity_change=quantity_change,
        reason=reason or None,
    )
    item.quantity_on_hand += quantity_change
    db.session.add(adjustment)
    db.session.commit()
    flash("Consumable stock updated.", "success")
    return redirect(url_for("equipment.consumable_detail", item_id=item.id))


@equipment_bp.route("/consumables/<int:item_id>/take", methods=["POST"])
@login_required
def take_consumable(item_id):
    item = ConsumableItem.query.get_or_404(item_id)
    user = current_user()
    settings = get_system_settings()
    quantity_taken = request.form.get("quantity_taken", type=int)
    reason = request.form.get("reason", "").strip()

    if user.role == "Viewer" or (user.role == "Student Crew" and not settings.students_can_log_consumables):
        flash("Your account cannot log consumable stock usage.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))
    if not quantity_taken or quantity_taken <= 0:
        flash("Enter how many units were taken.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))
    if item.quantity_on_hand - quantity_taken < 0:
        flash("There is not enough stock on hand for that request.", "error")
        return redirect(url_for("equipment.consumable_detail", item_id=item.id))

    adjustment = ConsumableAdjustment(
        consumable_id=item.id,
        user_id=user.id,
        quantity_change=-quantity_taken,
        reason=reason or "Taken from stock",
    )
    item.quantity_on_hand -= quantity_taken
    db.session.add(adjustment)
    db.session.commit()
    flash("Consumable usage logged.", "success")
    return redirect(url_for("equipment.consumable_detail", item_id=item.id))


@equipment_bp.route("/consumables/<int:item_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete_consumable(item_id):
    item = ConsumableItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Consumable item deleted.", "success")
    return redirect(url_for("equipment.consumables"))


@equipment_bp.route("/maintenance/print")
@role_required("Admin", "Teacher")
def maintenance_print():
    if not role_meets_requirement(current_user().role, get_system_settings().pdf_export_permission_role):
        flash("You do not have permission to export maintenance paperwork.", "error")
        return redirect(url_for("equipment.maintenance"))
    reports = DamageReport.query.order_by(DamageReport.created_at.desc()).all()
    return render_template("equipment/maintenance_print.html", reports=reports)


@equipment_bp.route("/maintenance/export.pdf")
@role_required("Admin", "Teacher")
def maintenance_pdf():
    if not role_meets_requirement(current_user().role, get_system_settings().pdf_export_permission_role):
        flash("You do not have permission to export maintenance paperwork.", "error")
        return redirect(url_for("equipment.maintenance"))
    reports = DamageReport.query.order_by(DamageReport.created_at.desc()).all()
    pdf_buffer, filename = build_maintenance_pdf(reports)
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@equipment_bp.route("/maintenance")
@role_required("Admin", "Teacher")
def maintenance():
    settings = get_system_settings()
    query = DamageReport.query
    if not settings.resolved_visible_in_queue:
        query = query.filter(DamageReport.status != "Resolved")
    reports = query.order_by(DamageReport.created_at.desc()).all()
    return render_template("equipment/maintenance.html", reports=reports, maintenance_statuses=configured_maintenance_statuses())


@equipment_bp.route("/scanner")
@login_required
def scanner():
    settings = get_system_settings()
    user = current_user()
    if user.role == "Student Crew" and not settings.student_crew_can_view_all_equipment:
        flash("Student Crew access to the equipment scanner is disabled in system settings.", "error")
        return redirect(url_for("dashboard"))
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
    settings = get_system_settings()
    user = current_user()
    if user.role == "Student Crew" and not settings.student_crew_can_view_all_equipment:
        flash("Student Crew access to equipment details is disabled in system settings.", "error")
        return redirect(url_for("dashboard"))
    item = Equipment.query.get_or_404(item_id)
    local_now = datetime.now()
    if not item.qr_code:
        generate_qr_code(item)
        db.session.commit()

    active_checkout = active_checkout_for_item(item.id)
    checkout_history = EquipmentCheckout.query.filter_by(equipment_id=item.id).order_by(EquipmentCheckout.checkout_time.desc()).limit(8).all()
    maintenance_reports = DamageReport.query.filter_by(equipment_id=item.id).order_by(DamageReport.created_at.desc()).limit(5).all()
    crew_users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    events = Event.query.order_by(Event.event_date.asc()).all()
    return render_template(
        "equipment/detail.html",
        item=item,
        active_checkout=active_checkout,
        checkout_history=checkout_history,
        maintenance_reports=maintenance_reports,
        crew_users=crew_users,
        events=events,
        now=local_now,
        public_qr_target=build_qr_target_url(item.id),
        scanned=request.args.get("scanner") == "1",
    )


@equipment_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    locations = active_storage_locations()
    settings = get_system_settings()
    categories = configured_equipment_categories()
    statuses = configured_equipment_statuses()
    if request.method == "POST":
        serial_number = optional_form_value("serial_number")
        location_value = optional_form_value("location")
        item = Equipment(
            name=request.form.get("name", "").strip(),
            category=request.form.get("category", "").strip(),
            description=request.form.get("description", "").strip(),
            serial_number=serial_number,
            condition=request.form.get("condition", "").strip() or "Good",
            location=location_value or None,
            status=request.form.get("status", "Available").strip(),
        )
        uploaded_image = save_image(request.files.get("image"))
        allowed_locations = valid_location_labels()

        if not item.name or item.category not in categories or item.status not in statuses:
            flash("Please complete the required equipment fields.", "error")
        elif settings.serial_numbers_required and not serial_number:
            flash("A serial number is required for equipment items.", "error")
        elif location_value and location_value not in allowed_locations:
            flash("Select a valid storage location from the admin-managed list.", "error")
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

    return render_template(
        "equipment/form.html",
        categories=categories,
        statuses=statuses,
        item=None,
        storage_locations=locations,
        current_location_managed=False,
        serial_numbers_required=settings.serial_numbers_required,
    )


@equipment_bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def edit(item_id):
    item = Equipment.query.get_or_404(item_id)
    locations = active_storage_locations()
    settings = get_system_settings()
    categories = configured_equipment_categories()
    statuses = configured_equipment_statuses()

    if request.method == "POST":
        serial_number = optional_form_value("serial_number")
        location_value = optional_form_value("location")
        previous_location = item.location
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        condition = request.form.get("condition", "").strip() or "Good"
        status = request.form.get("status", "Available").strip()
        replace_image = save_image(request.files.get("image"))
        remove_image = request.form.get("remove_image") == "on"
        existing_serial = None
        if serial_number:
            existing_serial = Equipment.query.filter(Equipment.serial_number == serial_number, Equipment.id != item.id).first()
        allowed_locations = valid_location_labels()
        if previous_location:
            allowed_locations.add(previous_location)

        if not name or category not in categories or status not in statuses:
            flash("Please complete the required equipment fields.", "error")
        elif settings.serial_numbers_required and not serial_number:
            flash("A serial number is required for equipment items.", "error")
        elif location_value and location_value not in allowed_locations:
            flash("Select a valid storage location from the admin-managed list.", "error")
        elif existing_serial:
            flash("That serial number is already assigned to another equipment item.", "error")
        elif replace_image is False:
            flash("Please upload a valid image file: png, jpg, jpeg, gif, or webp.", "error")
        else:
            item.name = name
            item.category = category
            item.description = description
            item.serial_number = serial_number
            item.condition = condition
            item.location = location_value
            item.status = status
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

    return render_template(
        "equipment/form.html",
        categories=categories,
        statuses=statuses,
        item=item,
        storage_locations=locations,
        current_location_managed=any(location.label == item.location for location in locations),
        serial_numbers_required=settings.serial_numbers_required,
    )


@equipment_bp.route("/<int:item_id>/maintenance-request", methods=["POST"])
@login_required
def maintenance_request(item_id):
    item = Equipment.query.get_or_404(item_id)
    reporter = current_user()
    settings = get_system_settings()
    description = request.form.get("description", "").strip()

    if not role_meets_requirement(reporter.role, settings.maintenance_submit_permission_role):
        flash("Your account does not have permission to submit maintenance requests.", "error")
        return redirect(url_for("equipment.detail", item_id=item.id))

    if not description:
        flash("Please describe what is wrong with the equipment.", "error")
        return redirect(url_for("equipment.detail", item_id=item.id))

    report = DamageReport(
        equipment_id=item.id,
        reported_by=reporter.id,
        description=description,
        status="Open",
    )
    if item.status not in {"Removed", "Under Repair"}:
        item.status = "Damaged"

    db.session.add(report)
    db.session.commit()

    teacher_emails = [teacher.email for teacher in User.query.filter_by(role="Teacher", is_active=True).order_by(User.name.asc()).all() if teacher.email]
    extra_recipients = alert_recipient_list(settings.maintenance_alert_recipients)
    teacher_emails = list(dict.fromkeys(teacher_emails + extra_recipients))
    notices = []
    for recipient_email in teacher_emails:
        try:
            sent = send_maintenance_request_email(recipient_email, report, reporter)
            if not sent:
                notices.append("Maintenance request saved, but email settings are incomplete so teacher notifications were skipped.")
                break
        except Exception as exc:
            notices.append(f"Maintenance request saved, but teacher email failed: {exc}")
            break

    for notice in notices:
        flash(notice, "error")

    flash("Maintenance request submitted and equipment marked for attention.", "success")
    return redirect(url_for("equipment.detail", item_id=item.id))


@equipment_bp.route("/maintenance/<int:report_id>/status", methods=["POST"])
@role_required("Admin", "Teacher")
def update_maintenance_status(report_id):
    report = DamageReport.query.get_or_404(report_id)
    new_status = request.form.get("status", "").strip()
    settings = get_system_settings()

    if not role_meets_requirement(current_user().role, settings.maintenance_resolve_permission_role):
        flash("Your account does not have permission to change maintenance statuses.", "error")
        return redirect(url_for("equipment.maintenance"))
    if new_status not in configured_maintenance_statuses():
        flash("Invalid maintenance status.", "error")
        return redirect(url_for("equipment.maintenance"))

    report.status = new_status
    if new_status == "Open":
        if report.equipment.status != "Removed":
            report.equipment.status = "Damaged"
    elif new_status == "Repairing":
        if report.equipment.status != "Removed":
            report.equipment.status = "Under Repair"
    elif new_status == "Resolved":
        unresolved_exists = DamageReport.query.filter(
            DamageReport.equipment_id == report.equipment_id,
            DamageReport.id != report.id,
            DamageReport.status != "Resolved",
        ).count()
        if report.equipment.status != "Removed" and not unresolved_exists:
            report.equipment.status = "Available"

    db.session.commit()
    flash("Maintenance status updated.", "success")
    return redirect(url_for("equipment.maintenance"))


@equipment_bp.route("/<int:item_id>/checkout", methods=["POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def checkout(item_id):
    item = Equipment.query.get_or_404(item_id)
    settings = get_system_settings()
    if not role_meets_requirement(current_user().role, settings.checkout_permission_role):
        flash("Your account does not have permission to check out equipment.", "error")
        return redirect(url_for("equipment.detail", item_id=item.id, scanner=1))
    active_checkout = active_checkout_for_item(item.id)
    user_id = request.form.get("user_id", type=int)
    event_id = request.form.get("event_id", type=int)
    assignee = db.session.get(User, user_id) if user_id else None
    event = db.session.get(Event, event_id) if event_id else None
    due_at_value = request.form.get("due_at", "").strip()

    try:
        due_at = parse_due_at(due_at_value)
    except ValueError:
        flash("Please enter a valid due date and time.", "error")
        return redirect(url_for("equipment.detail", item_id=item.id, scanner=1))

    if active_checkout:
        flash("This item is already checked out.", "error")
    elif item.status == "Removed":
        flash("Removed equipment cannot be checked out.", "error")
    elif item.status == "Damaged":
        flash("Damaged equipment cannot be checked out until it has been repaired.", "error")
    elif item.status == "Under Repair":
        flash("Equipment marked as Under Repair cannot be checked out.", "error")
    elif item.status != "Available":
        flash("Only equipment marked as Available can be checked out from this screen.", "error")
    elif not assignee or not assignee.is_active:
        flash("Select an active crew member or staff member.", "error")
    elif event_id and not event:
        flash("Select a valid event or leave the event field blank.", "error")
    elif settings.due_dates_required and not due_at:
        flash("A due date is required for equipment checkouts.", "error")
    elif due_at and due_at <= datetime.now():
        flash("The due date must be in the future.", "error")
    else:
        checkout_record = EquipmentCheckout(
            equipment_id=item.id,
            user_id=assignee.id,
            event_id=event.id if event else None,
            due_at=due_at,
            status="Checked Out",
        )
        item.status = "In Use"
        db.session.add(checkout_record)
        db.session.commit()
        try:
            send_equipment_checkout_email(checkout_record)
        except Exception:
            pass
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
        try:
            send_equipment_return_email(active_checkout)
        except Exception:
            pass
        flash(f"{item.name} has been checked back in.", "success")

    return redirect(url_for("equipment.detail", item_id=item.id, scanner=1))


@equipment_bp.route("/<int:item_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(item_id):
    item = Equipment.query.get_or_404(item_id)
    item.status = "Removed"
    db.session.commit()
    flash("Equipment marked as removed and hidden from the main inventory list.", "success")
    return redirect(url_for("equipment.index"))


@equipment_bp.route("/<int:item_id>/restore", methods=["POST"])
@role_required("Admin", "Teacher")
def restore(item_id):
    item = Equipment.query.get_or_404(item_id)
    item.status = "Available"
    db.session.commit()
    flash("Equipment restored to the live inventory list.", "success")
    return redirect(url_for("equipment.index", include_removed="on"))


@equipment_bp.route("/<int:item_id>/permanently-delete", methods=["POST"])
@role_required("Admin", "Teacher")
def permanently_delete(item_id):
    item = Equipment.query.get_or_404(item_id)

    if item.status != "Removed":
        flash("Only items already marked as removed can be permanently deleted.", "error")
        return redirect(url_for("equipment.index"))

    if active_checkout_for_item(item.id):
        flash("This item still has an active checkout and cannot be permanently deleted.", "error")
        return redirect(url_for("equipment.index", status="Removed"))

    if item.image_path:
        delete_image(item.image_path)
    if item.qr_code:
        delete_qr_code(item.qr_code)

    EquipmentCheckout.query.filter_by(equipment_id=item.id).delete(synchronize_session=False)
    DamageReport.query.filter_by(equipment_id=item.id).delete(synchronize_session=False)
    db.session.delete(item)
    db.session.commit()
    flash("Equipment permanently deleted, including its checkout and maintenance history.", "success")
    return redirect(url_for("equipment.index", status="Removed"))
