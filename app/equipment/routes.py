from flask import flash, redirect, render_template, request, url_for

from ..auth.routes import login_required, role_required
from ..extensions import db
from ..models import Equipment
from . import equipment_bp


CATEGORIES = ["Audio", "Lighting", "Cables", "Instruments", "Props", "AV Equipment", "Staging Gear"]
STATUSES = ["Available", "In Use", "Missing", "Damaged", "Under Repair"]


@equipment_bp.route("/")
@login_required
def index():
    query = Equipment.query
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    if search:
        query = query.filter(Equipment.name.ilike(f"%{search}%"))
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


@equipment_bp.route("/new", methods=["GET", "POST"])
@role_required("Admin", "Teacher", "Stage Manager")
def create():
    if request.method == "POST":
        item = Equipment(
            name=request.form.get("name", "").strip(),
            category=request.form.get("category", "").strip(),
            description=request.form.get("description", "").strip(),
            serial_number=request.form.get("serial_number", "").strip() or None,
            condition=request.form.get("condition", "").strip() or "Good",
            location=request.form.get("location", "").strip(),
            status=request.form.get("status", "Available").strip(),
        )

        if not item.name or item.category not in CATEGORIES or item.status not in STATUSES:
            flash("Please complete the required equipment fields.", "error")
        else:
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
        item.name = request.form.get("name", "").strip()
        item.category = request.form.get("category", "").strip()
        item.description = request.form.get("description", "").strip()
        item.serial_number = request.form.get("serial_number", "").strip() or None
        item.condition = request.form.get("condition", "").strip() or "Good"
        item.location = request.form.get("location", "").strip()
        item.status = request.form.get("status", "Available").strip()

        if not item.name or item.category not in CATEGORIES or item.status not in STATUSES:
            flash("Please complete the required equipment fields.", "error")
        else:
            db.session.commit()
            flash("Equipment updated.", "success")
            return redirect(url_for("equipment.index"))

    return render_template("equipment/form.html", categories=CATEGORIES, statuses=STATUSES, item=item)


@equipment_bp.route("/<int:item_id>/delete", methods=["POST"])
@role_required("Admin", "Teacher")
def delete(item_id):
    item = Equipment.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash("Equipment deleted.", "success")
    return redirect(url_for("equipment.index"))
