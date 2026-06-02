"""Shared Jinja2Templates instance.

Centralising the templates object lets every router share the same Jinja
environment, so globals (e.g. csrf_token) and filters (e.g. timeago) are
registered exactly once and available in every template.
"""

from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates

from app.core.csrf import generate_csrf_token


templates = Jinja2Templates(directory="app/templates")


def timeago(value: datetime | None) -> str:
    """Render a datetime as a short, human-friendly relative string."""
    if not value:
        return ""

    now = datetime.now(timezone.utc)
    # Stored timestamps are naive (UTC); make them comparable.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    delta = now - value
    seconds = int(delta.total_seconds())

    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"


# Available in every template as {{ csrf_token() }}
templates.env.globals["csrf_token"] = generate_csrf_token
templates.env.filters["timeago"] = timeago
