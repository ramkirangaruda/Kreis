"""Alumni service layer — School ERP."""

from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alumni import Alumni
from app.models.student import Student
from app.services.audit import log_action


class NotFoundError(Exception):
    """Raised when an alumni record is missing or out of scope."""


def _is_admin(user) -> bool:
    return user is not None and user.role.value == "KREIS_ADMIN"


def _check_scope(alum: Alumni, current_user):
    if not _is_admin(current_user) and alum.institution_id != current_user.institution_id:
        raise NotFoundError("Alumni record not found.")


# ── 1. list ────────────────────────────────────────────────────

async def list_alumni(db, current_user, institution_id=None, batch_year=None,
                      occupation=None, search=""):
    q = (
        select(Alumni)
        .options(selectinload(Alumni.institution))
        .order_by(Alumni.batch_year.desc(), Alumni.full_name)
    )
    if not _is_admin(current_user):
        q = q.where(Alumni.institution_id == current_user.institution_id)
    elif institution_id:
        q = q.where(Alumni.institution_id == institution_id)

    if batch_year:
        q = q.where(Alumni.batch_year == int(batch_year))
    if occupation:
        q = q.where(Alumni.current_occupation.ilike(f"%{occupation}%"))
    if search:
        term = f"%{search.strip()}%"
        q = q.where(or_(
            Alumni.full_name.ilike(term),
            Alumni.employer.ilike(term),
            Alumni.current_occupation.ilike(term),
        ))
    return (await db.execute(q)).scalars().all()


async def get_alumni_stats(db, current_user, institution_id=None) -> dict:
    base = select(func.count(Alumni.id))
    contact = select(func.count(Alumni.id)).where(
        or_(Alumni.phone.isnot(None), Alumni.email.isnot(None))
    )
    if not _is_admin(current_user):
        base = base.where(Alumni.institution_id == current_user.institution_id)
        contact = contact.where(Alumni.institution_id == current_user.institution_id)
    elif institution_id:
        base = base.where(Alumni.institution_id == institution_id)
        contact = contact.where(Alumni.institution_id == institution_id)

    total = (await db.execute(base)).scalar() or 0
    with_contact = (await db.execute(contact)).scalar() or 0
    pct = round(with_contact / total * 100, 1) if total else 0.0
    return {"total": total, "with_contact": with_contact, "contact_pct": pct}


# ── 2. get ─────────────────────────────────────────────────────

async def get_alumni(db, alumni_id, current_user) -> Alumni:
    alum = (await db.execute(
        select(Alumni)
        .options(selectinload(Alumni.institution), selectinload(Alumni.student))
        .where(Alumni.id == alumni_id)
    )).scalar_one_or_none()
    if not alum:
        raise NotFoundError("Alumni record not found.")
    _check_scope(alum, current_user)
    return alum


# ── helpers for create/update ──────────────────────────────────

_TEXT_FIELDS = [
    "full_name", "passed_class", "current_occupation", "employer",
    "higher_education_institution", "higher_education_course",
    "location_city", "location_state", "phone", "email",
    "linkedin_url", "notable_achievement",
]


def _clean(data: dict) -> dict:
    out = {}
    for f in _TEXT_FIELDS:
        if f in data:
            val = (data.get(f) or "").strip()
            out[f] = val or None
    return out


async def _resolve_institution(db, data, current_user):
    if not _is_admin(current_user):
        return current_user.institution_id
    # Admin: prefer linked student's institution, else explicit field.
    sid = data.get("student_id")
    if sid:
        student = await db.get(Student, int(sid))
        if student:
            return student.institution_id
    inst = data.get("institution_id")
    return int(inst) if inst else None


# ── 3. create ──────────────────────────────────────────────────

async def create_alumni(db, data, current_user, ip=None) -> Alumni:
    institution_id = await _resolve_institution(db, data, current_user)
    if not institution_id:
        raise ValueError("An institution is required for an alumni record.")

    if not data.get("full_name") or not str(data.get("full_name")).strip():
        raise ValueError("Full name is required.")
    if not data.get("batch_year"):
        raise ValueError("Batch year is required.")
    if not data.get("passed_class") or not str(data.get("passed_class")).strip():
        raise ValueError("Passed class is required.")

    sid = data.get("student_id")
    student_id = int(sid) if sid not in (None, "", "0") else None

    fields = _clean(data)
    alum = Alumni(
        institution_id=institution_id,
        student_id=student_id,
        batch_year=int(data["batch_year"]),
        updated_by_id=current_user.id,
        **fields,
    )
    db.add(alum)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="CREATE_ALUMNI",
        entity="Alumni", entity_id=alum.id,
        details={"name": alum.full_name, "batch": alum.batch_year}, ip_address=ip,
    )
    await db.commit()
    return alum


# ── 4. update ──────────────────────────────────────────────────

async def update_alumni(db, alumni_id, data, current_user, ip=None) -> Alumni:
    alum = await get_alumni(db, alumni_id, current_user)

    if data.get("batch_year"):
        alum.batch_year = int(data["batch_year"])
    sid = data.get("student_id")
    alum.student_id = int(sid) if sid not in (None, "", "0") else None

    for key, value in _clean(data).items():
        setattr(alum, key, value)
    alum.updated_by_id = current_user.id

    await log_action(
        db=db, user_id=current_user.id, action="UPDATE_ALUMNI",
        entity="Alumni", entity_id=alum.id, details={"name": alum.full_name}, ip_address=ip,
    )
    await db.commit()
    return alum
