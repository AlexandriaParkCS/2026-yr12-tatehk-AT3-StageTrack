from datetime import datetime
from zoneinfo import ZoneInfo

from .extensions import db
from .models import SystemSettings


DEFAULT_EQUIPMENT_CATEGORIES = ["Audio", "Lighting", "Cables", "Instruments", "Props", "AV Equipment", "Staging Gear"]
DEFAULT_EQUIPMENT_STATUSES = ["Available", "In Use", "Missing", "Damaged", "Under Repair", "Removed"]
DEFAULT_EVENT_VENUES = ["School Hall", "Theatre", "Gym", "Outdoor Stage"]
DEFAULT_EVENT_CREW_ROLES = ["Stage Manager", "Lighting Operator", "Sound Operator", "Crew", "Performer Support"]
DEFAULT_CONSUMABLE_CATEGORIES = ["Batteries", "Tape", "Adapters", "Cables", "Cleaning", "Lighting", "Audio", "General"]
DEFAULT_MAINTENANCE_STATUSES = ["Open", "Repairing", "Resolved"]
ROLE_ORDER = {"Viewer": 0, "Student Crew": 1, "Stage Manager": 2, "Teacher": 3, "Admin": 4}


def get_system_settings():
    settings = SystemSettings.query.order_by(SystemSettings.id.asc()).first()
    if not settings:
        settings = SystemSettings(
            equipment_categories="\n".join(DEFAULT_EQUIPMENT_CATEGORIES),
            equipment_statuses="\n".join(DEFAULT_EQUIPMENT_STATUSES),
            event_venues="\n".join(DEFAULT_EVENT_VENUES),
            event_crew_roles="\n".join(DEFAULT_EVENT_CREW_ROLES),
            consumable_categories="\n".join(DEFAULT_CONSUMABLE_CATEGORIES),
            maintenance_statuses="\n".join(DEFAULT_MAINTENANCE_STATUSES),
        )
        db.session.add(settings)
        db.session.commit()
    return settings


def parse_multiline_list(value, fallback):
    parsed = [line.strip() for line in (value or "").splitlines() if line.strip()]
    return parsed or list(fallback)


def role_meets_requirement(user_role, required_role):
    return ROLE_ORDER.get(user_role, -1) >= ROLE_ORDER.get(required_role, 999)


def settings_role_options():
    return ["Viewer", "Student Crew", "Stage Manager", "Teacher", "Admin"]


def equipment_categories():
    return parse_multiline_list(get_system_settings().equipment_categories, DEFAULT_EQUIPMENT_CATEGORIES)


def equipment_statuses():
    statuses = parse_multiline_list(get_system_settings().equipment_statuses, DEFAULT_EQUIPMENT_STATUSES)
    for required in ["Available", "In Use", "Missing", "Damaged", "Under Repair", "Removed"]:
        if required not in statuses:
            statuses.append(required)
    return statuses


def event_venues():
    return parse_multiline_list(get_system_settings().event_venues, DEFAULT_EVENT_VENUES)


def event_crew_roles():
    return parse_multiline_list(get_system_settings().event_crew_roles, DEFAULT_EVENT_CREW_ROLES)


def consumable_categories():
    return parse_multiline_list(get_system_settings().consumable_categories, DEFAULT_CONSUMABLE_CATEGORIES)


def maintenance_statuses():
    statuses = parse_multiline_list(get_system_settings().maintenance_statuses, DEFAULT_MAINTENANCE_STATUSES)
    if "Resolved" not in statuses:
        statuses.append("Resolved")
    return statuses


def alert_recipient_list(value):
    return [email.strip().lower() for email in (value or "").replace(",", "\n").splitlines() if email.strip()]


def format_datetime_for_display(value):
    if not value:
        return ""
    settings = get_system_settings()
    try:
        tz = ZoneInfo(settings.timezone_name)
    except Exception:
        tz = ZoneInfo("Australia/Sydney")

    dt_value = value
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    else:
        dt_value = dt_value.astimezone(tz)
    return dt_value.strftime(settings.datetime_format)


def subject_template(template, **values):
    try:
        return template.format(**values)
    except Exception:
        return template
