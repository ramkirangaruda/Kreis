"""Documents routes — circulars, memos, uploads, utility bills."""

from datetime import date

from fastapi import APIRouter, Request, Depends, Form, File, UploadFile, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.document import (
    CircularCategory, Urgency, RecipientType, DocType, BillType,
)

from app.services.institutions import list_institutions
from app.services.students import list_class_sections
from app.services.documents import (
    create_circular, list_circulars, get_circular, acknowledge_circular,
    unacknowledged_count, create_memo, list_memos,
    upload_document, list_documents, upload_utility_bill, list_utility_bills,
    NotFoundError,
)

router = APIRouter()

_ADMIN = require_role(["KREIS_ADMIN"])
_PRINCIPAL = require_role(["PRINCIPAL"])
_MANAGER = require_role(["KREIS_ADMIN", "PRINCIPAL"])


def _parse_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except (ValueError, TypeError):
        return None


def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


# ── Landing ────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def documents_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    circulars = (await list_circulars(db, current_user))[:5]
    memos = (await list_memos(db, current_user))[:5]
    docs = (await list_documents(db, current_user))[:5]
    unread = await unacknowledged_count(db, current_user)
    return templates.TemplateResponse(
        "documents/index.html",
        {
            "request": request, "current_user": current_user,
            "circulars": circulars, "memos": memos, "documents": docs,
            "unread": unread,
        },
    )


# ── Circulars ──────────────────────────────────────────────────

@router.get("/circulars", response_class=HTMLResponse)
async def circulars_list(
    request: Request,
    category: str = "",
    urgency: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    circulars = await list_circulars(db, current_user, category or None, urgency or None)
    ctx = {
        "request": request, "current_user": current_user, "circulars": circulars,
        "categories": [c.value for c in CircularCategory],
        "urgencies": [u.value for u in Urgency],
        "selected_category": category, "selected_urgency": urgency,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/circular_rows.html", ctx)
    return templates.TemplateResponse("documents/circulars.html", ctx)


@router.get("/circulars/new", response_class=HTMLResponse)
async def new_circular_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    institutions = await list_institutions(db)
    return templates.TemplateResponse(
        "documents/circular_form.html",
        {
            "request": request, "current_user": current_user,
            "institutions": institutions,
            "categories": [c.value for c in CircularCategory],
            "urgencies": [u.value for u in Urgency],
        },
    )


@router.post("/circulars")
async def create_circular_route(
    request: Request,
    title: str = Form(...),
    content: str = Form(""),
    category: str = Form(...),
    urgency: str = Form(...),
    institution_id: str = Form(""),
    csrf_token: str = Form(""),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await create_circular(
            db,
            {"title": title, "content": content, "category": category,
             "urgency": urgency, "institution_id": _to_int(institution_id)},
            file, current_user, ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/documents/circulars/new?error={exc}", status_code=303)
    return RedirectResponse("/documents/circulars", status_code=303)


@router.get("/circulars/{circular_id}", response_class=HTMLResponse)
async def circular_detail(
    circular_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        circular, acknowledged = await get_circular(db, circular_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Circular not found")
    return templates.TemplateResponse(
        "documents/circular_detail.html",
        {
            "request": request, "current_user": current_user,
            "circular": circular, "acknowledged": acknowledged,
        },
    )


@router.post("/circulars/{circular_id}/acknowledge")
async def acknowledge_route(
    circular_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_PRINCIPAL),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await acknowledge_circular(
            db, circular_id, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Circular not found")
    return RedirectResponse(f"/documents/circulars/{circular_id}", status_code=303)


# ── Memos ──────────────────────────────────────────────────────

@router.get("/memos", response_class=HTMLResponse)
async def memos_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memos = await list_memos(db, current_user)
    return templates.TemplateResponse(
        "documents/memos.html",
        {"request": request, "current_user": current_user, "memos": memos},
    )


@router.get("/memos/new", response_class=HTMLResponse)
async def new_memo_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    class_sections = await list_class_sections(db, current_user)
    users = []
    if current_user.institution_id:
        users = (await db.execute(
            select(User).where(
                User.institution_id == current_user.institution_id,
                User.is_active.is_(True),
            ).order_by(User.full_name)
        )).scalars().all()
    return templates.TemplateResponse(
        "documents/memo_form.html",
        {
            "request": request, "current_user": current_user,
            "recipient_types": [r.value for r in RecipientType],
            "class_sections": class_sections, "users": users,
        },
    )


@router.post("/memos")
async def create_memo_route(
    request: Request,
    title: str = Form(...),
    content: str = Form(...),
    recipient_type: str = Form(...),
    recipient_class_id: str = Form(""),
    recipient_user_id: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await create_memo(
            db,
            {"title": title, "content": content, "recipient_type": recipient_type,
             "recipient_class_id": recipient_class_id, "recipient_user_id": recipient_user_id},
            current_user, ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/documents/memos/new?error={exc}", status_code=303)
    return RedirectResponse("/documents/memos", status_code=303)


# ── Document upload ────────────────────────────────────────────

@router.get("/upload", response_class=HTMLResponse)
async def upload_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.student import Student
    students = []
    if current_user.institution_id:
        students = (await db.execute(
            select(Student).where(
                Student.institution_id == current_user.institution_id,
                Student.is_active.is_(True),
            ).order_by(Student.full_name)
        )).scalars().all()
    recent = (await list_documents(db, current_user))[:8]
    return templates.TemplateResponse(
        "documents/upload.html",
        {
            "request": request, "current_user": current_user,
            "doc_types": [d.value for d in DocType], "students": students,
            "recent": recent,
        },
    )


@router.post("/upload")
async def upload_route(
    request: Request,
    title: str = Form(...),
    doc_type: str = Form(...),
    tags: str = Form(""),
    student_id: str = Form(""),
    csrf_token: str = Form(""),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        doc = await upload_document(
            db, file, doc_type, title, tags, student_id or None,
            current_user, ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/documents/upload?error={exc}", status_code=303)
    return RedirectResponse(f"/documents/search?q={doc.title}", status_code=303)


# ── Search ─────────────────────────────────────────────────────

@router.get("/search", response_class=HTMLResponse)
async def search_documents(
    request: Request,
    q: str = "",
    doc_type: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    documents = await list_documents(
        db, current_user, doc_type=doc_type or None, search=q
    )
    ctx = {
        "request": request, "current_user": current_user,
        "documents": documents, "q": q,
        "doc_types": [d.value for d in DocType], "selected_doc_type": doc_type,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/document_results.html", ctx)
    return templates.TemplateResponse("documents/search.html", ctx)


# ── Utility bills ──────────────────────────────────────────────

@router.get("/bills", response_class=HTMLResponse)
async def bills_list(
    request: Request,
    bill_type: str = "",
    year: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    bills = await list_utility_bills(db, current_user, bill_type or None, _to_int(year))
    return templates.TemplateResponse(
        "documents/bills.html",
        {
            "request": request, "current_user": current_user, "bills": bills,
            "bill_types": [b.value for b in BillType],
            "selected_bill_type": bill_type, "selected_year": year,
            "is_admin": current_user.role.value == "KREIS_ADMIN",
        },
    )


@router.post("/bills")
async def upload_bill_route(
    request: Request,
    bill_type: str = Form(...),
    bill_month: str = Form(...),
    amount: str = Form(""),
    csrf_token: str = Form(""),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    month = _parse_date(bill_month) or _parse_date(bill_month + "-01")
    if month is None:
        return RedirectResponse("/documents/bills?error=Invalid+month", status_code=303)
    month = month.replace(day=1)
    try:
        await upload_utility_bill(
            db, file, bill_type, month, amount, current_user,
            ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/documents/bills?error={exc}", status_code=303)
    return RedirectResponse("/documents/bills", status_code=303)
