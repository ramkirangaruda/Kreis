import json
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    user_id: int,
    action: str,
    entity: str,
    entity_id: int,
    details: dict | None = None,
    ip_address: str | None = None
):
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=json.dumps(details) if details else None,
        ip_address=ip_address
    )

    db.add(log)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


async def get_audit_logs(
    db: AsyncSession,
    user_id: int | None = None,
    action: str | None = None,
    entity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Return a paginated, filtered slice of audit logs (admin view).

    Returns a dict with `logs`, `total`, `page`, `pages`.
    """
    filters = []
    if user_id:
        filters.append(AuditLog.user_id == user_id)
    if action:
        filters.append(AuditLog.action == action)
    if entity:
        filters.append(AuditLog.entity == entity)

    start = _parse_date(date_from)
    if start:
        filters.append(AuditLog.created_at >= start)
    end = _parse_date(date_to)
    if end:
        # Inclusive of the whole end day.
        filters.append(AuditLog.created_at < end + timedelta(days=1))

    count_query = select(func.count(AuditLog.id))
    if filters:
        count_query = count_query.where(*filters)
    total = (await db.execute(count_query)).scalar() or 0

    page = max(page, 1)
    pages = max((total + per_page - 1) // per_page, 1)

    query = (
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    if filters:
        query = query.where(*filters)

    logs = (await db.execute(query)).scalars().all()

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "pages": pages,
    }


async def list_audit_filters(db: AsyncSession) -> dict:
    """Distinct actions and entities, for filter dropdowns."""
    actions = (
        await db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))
    ).scalars().all()
    entities = (
        await db.execute(select(AuditLog.entity).distinct().order_by(AuditLog.entity))
    ).scalars().all()
    return {"actions": actions, "entities": entities}
