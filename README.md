# Backstage Equipment & Production Management System

Phase 1 Flask scaffold for a school production and backstage operations platform.

## What's included

- Session-based authentication with role support
- Admin user management for access control, roles, and password resets
- Dashboard with inventory and event summary cards
- Equipment inventory CRUD with search and category filters
- Event management CRUD with production schedule fields
- Crew task management with role-aware views and status updates
- Mobile-friendly Jinja templates and shared styling
- SQLite-backed SQLAlchemy models designed for future expansion

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The app creates `instance/backstage.db` automatically on first run.

## Default workflow

1. Register the first admin or teacher account.
2. Add equipment inventory items.
3. Create events and setup times.
4. Assign tasks to crew members.
5. Use the dashboard to monitor upcoming work.

## Suggested next phases

- QR code generation and scan-based check-in/check-out
- Crew task assignment and checklist tracking
- Damage reports with image uploads
- Email notifications and password reset flow
- Migration tooling for PostgreSQL support
