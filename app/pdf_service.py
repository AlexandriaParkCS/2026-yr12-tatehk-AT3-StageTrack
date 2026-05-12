from io import BytesIO

from .system_settings_service import get_system_settings


def _load_reportlab():
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, LETTER, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ModuleNotFoundError as exc:
        raise RuntimeError("PDF export is not available until the reportlab dependency is installed.") from exc

    return {
        "colors": colors,
        "A4": A4,
        "LETTER": LETTER,
        "landscape": landscape,
        "styles": getSampleStyleSheet(),
        "Paragraph": Paragraph,
        "SimpleDocTemplate": SimpleDocTemplate,
        "Spacer": Spacer,
        "Table": Table,
        "TableStyle": TableStyle,
    }


def _build_pdf(title, subtitle, headers, rows, filename_hint):
    rl = _load_reportlab()
    settings = get_system_settings()
    buffer = BytesIO()
    page_size = rl["A4"] if settings.pdf_paper_size.upper() == "A4" else rl["LETTER"]
    doc = rl["SimpleDocTemplate"](
        buffer,
        pagesize=rl["landscape"](page_size),
        leftMargin=28,
        rightMargin=28,
        topMargin=28,
        bottomMargin=28,
    )
    styles = rl["styles"]
    story = []
    if settings.pdf_show_header:
        story.append(rl["Paragraph"](f"<b>{settings.pdf_header_text}</b>", styles["Title"]))
    story.extend(
        [
            rl["Paragraph"](title, styles["Heading2"]),
            rl["Paragraph"](subtitle, styles["BodyText"]),
            rl["Spacer"](1, 14),
        ]
    )

    data = [headers] + rows
    table = rl["Table"](data, repeatRows=1)
    table.setStyle(
        rl["TableStyle"](
            [
                ("BACKGROUND", (0, 0), (-1, 0), rl["colors"].HexColor("#1d1f24")),
                ("TEXTCOLOR", (0, 0), (-1, 0), rl["colors"].HexColor("#ffd33d")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, rl["colors"].HexColor("#cfcfcf")),
                ("BACKGROUND", (0, 1), (-1, -1), rl["colors"].white),
                ("TEXTCOLOR", (0, 1), (-1, -1), rl["colors"].black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LEADING", (0, 0), (-1, -1), 11),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl["colors"].white, rl["colors"].HexColor("#f7f7f7")]),
            ]
        )
    )
    story.append(table)
    story.append(rl["Spacer"](1, 12))
    if settings.pdf_include_signatures:
        story.append(rl["Paragraph"]("Signature: ________________________________", styles["BodyText"]))
        story.append(rl["Spacer"](1, 8))
    story.append(rl["Paragraph"](settings.pdf_footer_text, styles["BodyText"]))
    doc.build(story)
    buffer.seek(0)
    return buffer, filename_hint


def build_maintenance_pdf(reports):
    settings = get_system_settings()
    headers = ["Equipment", "Reporter", "Location", "Status", "Reported", "Issue"]
    if settings.pdf_include_notes:
        headers.append("Notes")
    rows = [
        [
            report.equipment.name,
            report.reporter.name,
            report.equipment.location or "Not set",
            report.status,
            report.created_at.strftime("%d %b %Y %I:%M %p"),
            report.description,
            "",
        ]
        for report in reports
    ] or [["No maintenance requests", "", "", "", "", "", ""]]
    if not settings.pdf_include_notes:
        rows = [row[:-1] for row in rows]
    return _build_pdf(
        "Maintenance Sheet",
        "StageTrack maintenance queue export",
        headers,
        rows,
        "stagetrack-maintenance-sheet.pdf",
    )


def build_event_equipment_pdf(event, linked_checkouts, generated_at):
    settings = get_system_settings()
    headers = ["Equipment", "Category", "Assigned to", "Location", "Out", "Returned"]
    if settings.pdf_include_checkboxes:
        headers.append("Tick")
    if settings.pdf_include_notes:
        headers.append("Notes")
    rows = [
        [
            checkout.equipment.name,
            checkout.equipment.category,
            checkout.user.name,
            checkout.equipment.location or "Not set",
            checkout.checkout_time.strftime("%d %b %Y %I:%M %p"),
            checkout.return_time.strftime("%d %b %Y %I:%M %p") if checkout.return_time else "Still checked out",
            "[ ]",
            "",
        ]
        for checkout in linked_checkouts
    ] or [["No linked equipment", "", "", "", "", "", "", ""]]
    if not settings.pdf_include_notes:
        rows = [row[:-1] for row in rows]
    if not settings.pdf_include_checkboxes:
        checkbox_index = len(rows[0]) - (1 if settings.pdf_include_notes else 0) - 1
        rows = [row[:checkbox_index] + row[checkbox_index + 1 :] for row in rows]
    subtitle = (
        f"{event.name} | Venue: {event.venue} | Event: {event.event_date.strftime('%d %b %Y %I:%M %p')} | "
        f"Generated: {generated_at.strftime('%d %b %Y %I:%M %p')}"
    )
    return _build_pdf(
        f"{event.name} Equipment Sheet",
        subtitle,
        headers,
        rows,
        f"stagetrack-{event.name.lower().replace(' ', '-')}-equipment-sheet.pdf",
    )


def build_kit_checkout_pdf(kit, active_checkout_map, generated_at):
    settings = get_system_settings()
    headers = ["Item", "Category", "Location", "Current holder"]
    if settings.pdf_include_checkboxes:
        headers.append("Tick")
    if settings.pdf_include_notes:
        headers.append("Notes")
    rows = [
        [
            link.equipment.name,
            link.equipment.category,
            link.equipment.location or "Not set",
            active_checkout_map[link.equipment.id].user.name if link.equipment.id in active_checkout_map else "Not checked out",
            "[ ]",
            "",
        ]
        for link in kit.items
    ] or [["No kit items", "", "", "", "", ""]]
    if not settings.pdf_include_notes:
        rows = [row[:-1] for row in rows]
    if not settings.pdf_include_checkboxes:
        checkbox_index = len(rows[0]) - (1 if settings.pdf_include_notes else 0) - 1
        rows = [row[:checkbox_index] + row[checkbox_index + 1 :] for row in rows]
    subtitle = f"{kit.name} | Generated: {generated_at.strftime('%d %b %Y %I:%M %p')}"
    return _build_pdf(
        f"{kit.name} Checkout Sheet",
        subtitle,
        headers,
        rows,
        f"stagetrack-{kit.name.lower().replace(' ', '-')}-kit-sheet.pdf",
    )
