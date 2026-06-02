"""Stateless CSRF token helpers.

Tokens are signed with the application SECRET_KEY using itsdangerous'
URLSafeTimedSerializer. Because they are signed (not stored), validation only
needs the signature and an age check — no server-side session is required.
"""

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.core.config import settings


_SALT = "kreis-csrf"

_serializer = URLSafeTimedSerializer(settings.secret_key, salt=_SALT)


def generate_csrf_token() -> str:
    """Return a fresh signed CSRF token."""
    return _serializer.dumps("csrf")


def validate_csrf_token(token: str | None, max_age: int = 3600) -> bool:
    """Validate a CSRF token. Returns True only for a well-formed,
    unexpired token signed with our SECRET_KEY."""
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=max_age)
        return True
    except (BadSignature, SignatureExpired):
        return False
