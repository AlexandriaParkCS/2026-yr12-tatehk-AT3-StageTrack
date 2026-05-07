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
- Render deployment support with env-based database config

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The app creates `instance/backstage.db` automatically on first run.

## Deploy on Render

Render's Flask docs currently recommend:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app`

This repo now includes a [render.yaml](C:/Users/think/Documents/GitHub/2026-yr12-tatehk-AT3-StageTrack/render.yaml:1) Blueprint and reads `DATABASE_URL` / `SECRET_KEY` from environment variables for production.

### Important production notes

- Do not use SQLite on Render for real app data. Render's filesystem is ephemeral, so this app is configured to use Postgres in production.
- Uploaded images and generated QR files are still stored on the local filesystem right now, which also means they are ephemeral on Render until you move them to cloud storage or a persistent disk.

### Quick Render setup

1. Push this repo to GitHub.
2. In Render, create a new Blueprint and point it at this repo.
3. Let Render create:
   - A web service for the Flask app
   - A Postgres database
4. Set the `SECRET_KEY` value when prompted.
5. After the first deploy, open the site and create the first admin account.
6. Go to Admin > Email Settings and enter your SMTP details.

### Manual service settings

If you prefer to create the service without the Blueprint:

- Runtime: `Python`
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app`
- Environment variables:
  - `DATABASE_URL` = your Render Postgres internal connection string
  - `SECRET_KEY` = a long random secret
  - `PREFERRED_URL_SCHEME` = `https`
  - `SESSION_COOKIE_SECURE` = `true`

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
