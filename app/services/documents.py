"""Documents service layer — circulars, memos, uploads, utility bills."""

from datetime import date

from sqlalchemy import select, or_, extract
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.student import Student
from app.models.document import (
    Circular, CircularAcknowledgement, Memo, UploadedDocument, UtilityBill,
    CircularCategory, Urgency, RecipientType, DocType, OcrStatus, BillType,
)
from app.core.storage import save_upload
from app.services.audit import log_action


class NotFoundError(Exception):
    """Raised when an entity is missing or outside the caller's scope."""


def _is_admin(user) -> bool:
    return user is not None and user.role.value == "KREIS_ADMIN"


def _enum_or_none(enum_cls, value):
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _has_file(file) -> bool:
    return file is not None and getattr(file, "filename", "")


# ── 1/2/3. Circulars ───────────────────────────────────────────

async def create_circular(db, data, file, current_user, ip=None):
    category = _enum_or_none(CircularCategory, data.get("category"))
    urgency = _enum_or_none(Urgency, data.get("urgency"))
    if category is None or urgency is None:
        raise ValueError("Category and urgency are required.")

    file_url = None
    if _has_file(file):
        file_url = await save_upload(file, "circulars")

    institution_id = data.get("institution_id")  # None ⇒ broadcast to all

    circular = Circular(
        institution_id=institution_id,
        title=data["title"].strip(),
        content=(data.get("content") or "").strip() or None,
        file_url=file_url,
        category=category,
        urgency=urgency,
        uploaded_by_id=current_user.id,
    )
    db.add(circular)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="CREATE_CIRCULAR",
        entity="Circular", entity_id=circular.id,
        details={"title": circular.title, "broadcast": institution_id is None},
        ip_address=ip,
    )
    await db.commit()
    return circular


async def list_circulars(db, current_user, category=None, urgency=None):
    q = (
        select(Circular)
        .options(selectinload(Circular.institution), selectinload(Circular.acknowledgements))
        .order_by(Circular.created_at.desc())
    )
    if not _is_admin(current_user):
        q = q.where(
            or_(
                Circular.institution_id == current_user.institution_id,
                Circular.institution_id.is_(None),
            )
        )
    cat = _enum_or_none(CircularCategory, category)
    if cat:
        q = q.where(Circular.category == cat)
    urg = _enum_or_none(Urgency, urgency)
    if urg:
        q = q.where(Circular.urgency == urg)
    return (await db.execute(q)).scalars().all()


async def get_circular(db, circular_id, current_user):
    circular = (await db.execute(
        select(Circular)
        .options(
            selectinload(Circular.institution),
            selectinload(Circular.acknowledgements).selectinload(CircularAcknowledgement.institution),
        )
        .where(Circular.id == circular_id)
    )).scalar_one_or_none()
    if not circular:
        raise NotFoundError("Circular not found.")
    if not _is_admin(current_user):
        if circular.institution_id not in (None, current_user.institution_id):
            raise NotFoundError("Circular not found.")
    acknowledged = any(
        a.institution_id == current_user.institution_id for a in circular.acknowledgements
    )
    return circular, acknowledged


async def acknowledge_circular(db, circular_id, current_user, ip=None):
    circular = await db.get(Circular, circular_id)
    if not circular:
        raise NotFoundError("Circular not found.")

    existing = (await db.execute(
        select(CircularAcknowledgement).where(
            CircularAcknowledgement.circular_id == circular_id,
            CircularAcknowledgement.institution_id == current_user.institution_id,
        )
    )).scalar_one_or_none()
    if existing:
        return existing  # already acknowledged — no-op

    ack = CircularAcknowledgement(
        circular_id=circular_id,
        institution_id=current_user.institution_id,
        acknowledged_by_id=current_user.id,
    )
    db.add(ack)
    await log_action(
        db=db, user_id=current_user.id, action="ACKNOWLEDGE_CIRCULAR",
        entity="Circular", entity_id=circular_id, ip_address=ip,
    )
    await db.commit()
    return ack


async def unacknowledged_count(db, current_user) -> int:
    """Broadcast/own circulars this institution has not yet acknowledged."""
    if _is_admin(current_user) or current_user.institution_id is None:
        return 0
    visible = (await db.execute(
        select(Circular.id).where(
            or_(
                Circular.institution_id == current_user.institution_id,
                Circular.institution_id.is_(None),
            )
        )
    )).scalars().all()
    acked = (await db.execute(
        select(CircularAcknowledgement.circular_id).where(
            CircularAcknowledgement.institution_id == current_user.institution_id
        )
    )).scalars().all()
    return len(set(visible) - set(acked))


# ── 4/5. Memos ─────────────────────────────────────────────────

async def create_memo(db, data, current_user, ip=None):
    recipient_type = _enum_or_none(RecipientType, data.get("recipient_type"))
    if recipient_type is None:
        raise ValueError("A valid recipient type is required.")
    if not current_user.institution_id:
        raise ValueError("Memos must be sent from within an institution.")

    def _int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (ValueError, TypeError):
            return None

    memo = Memo(
        sender_id=current_user.id,
        institution_id=current_user.institution_id,
        title=data["title"].strip(),
        content=data["content"].strip(),
        recipient_type=recipient_type,
        recipient_class_id=_int(data.get("recipient_class_id")) if recipient_type == RecipientType.SPECIFIC_CLASS else None,
        recipient_user_id=_int(data.get("recipient_user_id")) if recipient_type == RecipientType.INDIVIDUAL else None,
    )
    db.add(memo)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="CREATE_MEMO",
        entity="Memo", entity_id=memo.id, details={"title": memo.title}, ip_address=ip,
    )
    await db.commit()
    return memo


async def list_memos(db, current_user):
    q = (
        select(Memo)
        .options(selectinload(Memo.sender), selectinload(Memo.recipient_class))
        .order_by(Memo.created_at.desc())
    )
    if not _is_admin(current_user):
        q = q.where(Memo.institution_id == current_user.institution_id)
    return (await db.execute(q)).scalars().all()


# ── 6/7. Uploaded documents ────────────────────────────────────

async def upload_document(db, file, doc_type, title, tags, student_id=None,
                          current_user=None, ip=None):
    if not _has_file(file):
        raise ValueError("A file is required.")
    if not current_user.institution_id:
        raise ValueError("Document upload requires an institution context.")

    dt = _enum_or_none(DocType, doc_type) or DocType.OTHER
    file_url = await save_upload(file, "documents")

    sid = None
    if student_id not in (None, "", "0"):
        try:
            sid = int(student_id)
        except (ValueError, TypeError):
            sid = None

    doc = UploadedDocument(
        institution_id=current_user.institution_id,
        title=title.strip(),
        doc_type=dt,
        file_url=file_url,
        file_name=file.filename or "file",
        ocr_status=OcrStatus.PENDING,
        student_id=sid,
        tags=(tags or "").strip() or None,
        uploaded_by_id=current_user.id,
    )
    db.add(doc)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="UPLOAD_DOCUMENT",
        entity="UploadedDocument", entity_id=doc.id,
        details={"title": doc.title, "type": dt.value}, ip_address=ip,
    )
    await db.commit()
    return doc


async def list_documents(db, current_user, doc_type=None, student_id=None, search=""):
    q = (
        select(UploadedDocument)
        .options(selectinload(UploadedDocument.student))
        .order_by(UploadedDocument.created_at.desc())
    )
    if not _is_admin(current_user):
        q = q.where(UploadedDocument.institution_id == current_user.institution_id)

    dt = _enum_or_none(DocType, doc_type)
    if dt:
        q = q.where(UploadedDocument.doc_type == dt)
    if student_id:
        q = q.where(UploadedDocument.student_id == int(student_id))
    if search:
        term = f"%{search.strip()}%"
        q = q.where(or_(
            UploadedDocument.title.ilike(term),
            UploadedDocument.tags.ilike(term),
            UploadedDocument.ocr_text.ilike(term),
        ))
    return (await db.execute(q)).scalars().all()


# ── 8/9. Utility bills ─────────────────────────────────────────

async def upload_utility_bill(db, file, bill_type, bill_month, amount,
                              current_user, ip=None):
    bt = _enum_or_none(BillType, bill_type)
    if bt is None:
        raise ValueError("A valid bill type is required.")
    if not current_user.institution_id:
        raise ValueError("Utility bills must belong to an institution.")

    file_url = None
    if _has_file(file):
        file_url = await save_upload(file, "bills")

    amt = None
    if amount not in (None, ""):
        try:
            amt = float(amount)
        except (ValueError, TypeError):
            amt = None

    bill = UtilityBill(
        institution_id=current_user.institution_id,
        bill_type=bt,
        bill_month=bill_month,
        amount=amt,
        file_url=file_url,
        uploaded_by_id=current_user.id,
    )
    db.add(bill)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="UPLOAD_UTILITY_BILL",
        entity="UtilityBill", entity_id=bill.id,
        details={"type": bt.value, "month": bill_month.isoformat()}, ip_address=ip,
    )
    await db.commit()
    return bill


async def list_utility_bills(db, current_user, bill_type=None, year=None):
    q = (
        select(UtilityBill)
        .options(selectinload(UtilityBill.institution))
        .order_by(UtilityBill.bill_month.desc())
    )
    if not _is_admin(current_user):
        q = q.where(UtilityBill.institution_id == current_user.institution_id)
    bt = _enum_or_none(BillType, bill_type)
    if bt:
        q = q.where(UtilityBill.bill_type == bt)
    if year:
        q = q.where(extract("year", UtilityBill.bill_month) == int(year))
    return (await db.execute(q)).scalars().all()
