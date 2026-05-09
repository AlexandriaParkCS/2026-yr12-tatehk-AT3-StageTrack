from .extensions import db
from .models import SiteSettings


def get_site_settings():
    settings = SiteSettings.query.order_by(SiteSettings.id.asc()).first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
        db.session.commit()
    return settings
