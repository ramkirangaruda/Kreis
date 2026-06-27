"""Demo seed data for KREIS IMS.

Idempotent: existing records (matched by natural keys) are left untouched, so
the script can safely be re-run. Run with:

    python scripts/seed_demo.py
"""

import asyncio
import random
from datetime import datetime, timedelta, date

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password

from app.models.user import User, UserRole
from app.models.institution import Institution
from app.models.asset import Asset, AssetCategory
from app.models.inventory import InventoryItem, AssetMovement, MovementType

# ── School ERP models ──
from app.models.student import (
    AcademicYear, ClassSection, Student, StudentDemographics, Gender, CasteCategory,
)
from app.models.attendance import StudentAttendance, StudentAttendanceStatus
from app.models.academic import (
    Subject, Exam, ExamResult, CompetitiveExamResult, ExamType, CompetitiveExamName,
)
from app.models.alumni import Alumni
from app.models.document import Circular, CircularCategory, Urgency
from app.services.academics import grade_for


CATEGORIES = [
    ("A", "Student Welfare & Uniform Assets"),
    ("B", "Library Management Assets"),
    ("C", "Classroom Furniture Assets"),
    ("D", "Smart Classroom Assets"),
    ("E", "Computer Laboratory Assets"),
    ("F", "Science Laboratory Assets"),
    ("G", "Hostel Assets & Amenities"),
]

# 5 realistic asset names per category (35 total).
ASSETS_BY_CATEGORY = {
    "A": ["School Uniform Set", "School Shoes", "Socks Pair", "Sweater", "School Bag"],
    "B": ["Bookshelf", "Reading Table", "Library Chair", "Book Trolley", "Catalogue Cabinet"],
    "C": ["Student Desk", "Student Chair", "Teacher Table", "Blackboard", "Notice Board"],
    "D": ["Interactive Whiteboard", "Projector", "Projector Screen", "Smart TV", "Speaker System"],
    "E": ["Desktop Computer", "LCD Monitor", "Keyboard", "UPS Unit", "Network Switch"],
    "F": ["Microscope", "Test Tube Set", "Bunsen Burner", "Lab Stool", "Chemical Cabinet"],
    "G": ["Bunk Bed", "Mattress", "Steel Almirah", "Study Lamp", "Water Purifier"],
}

INSTITUTIONS = [
    ("Rajiv Gandhi HS", "RGH-01", "District 3"),
    ("Nehru Model School", "NMS-01", "District 1"),
    ("Ambedkar Vidyalaya", "AV-01", "District 5"),
    ("Gandhi Govt School", "GGS-01", "District 2"),
    ("Saraswati HS", "SHS-01", "District 6"),
]

# (email, full_name, institution_code)
PRINCIPALS = [
    ("principal.rgh@kreis.edu", "Principal — Rajiv Gandhi HS", "RGH-01"),
    ("principal.nms@kreis.edu", "Principal — Nehru Model School", "NMS-01"),
    ("principal.av@kreis.edu", "Principal — Ambedkar Vidyalaya", "AV-01"),
    ("principal.ggs@kreis.edu", "Principal — Gandhi Govt School", "GGS-01"),
    ("principal.shs@kreis.edu", "Principal — Saraswati HS", "SHS-01"),
]

STUDENT_NAMES = [
    "Aarav Sharma", "Diya Patel", "Vivaan Reddy", "Ananya Iyer", "Arjun Nair",
    "Saanvi Rao", "Reyansh Gupta", "Ishaan Kumar", "Aadhya Menon", "Kabir Singh",
    "Myra Joshi", "Vihaan Das", "Anika Bose", "Aryan Pillai", "Navya Shetty",
]


async def _get_or_create_categories(db):
    for code, name in CATEGORIES:
        exists = (
            await db.execute(select(AssetCategory).where(AssetCategory.code == code))
        ).scalar_one_or_none()
        if not exists:
            db.add(AssetCategory(code=code, name=name))
    await db.flush()


async def _get_or_create_admin(db):
    exists = (
        await db.execute(select(User).where(User.email == "admin@kreis.edu"))
    ).scalar_one_or_none()
    if not exists:
        db.add(User(
            email="admin@kreis.edu",
            hashed_password=hash_password("changeme123"),
            full_name="KREIS Admin",
            role=UserRole.KREIS_ADMIN,
        ))
    await db.flush()


async def _get_or_create_institutions(db):
    for name, code, district in INSTITUTIONS:
        exists = (
            await db.execute(select(Institution).where(Institution.code == code))
        ).scalar_one_or_none()
        if not exists:
            db.add(Institution(
                name=name,
                code=code,
                district=district,
                address=f"{name}, {district}, Karnataka",
                is_active=True,
            ))
    await db.flush()


async def _get_or_create_principals(db, inst_by_code):
    for email, full_name, code in PRINCIPALS:
        exists = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if not exists:
            db.add(User(
                email=email,
                hashed_password=hash_password("School@1234"),
                full_name=full_name,
                role=UserRole.PRINCIPAL,
                institution_id=inst_by_code[code].id,
                password_change_required=True,
            ))
    await db.flush()


async def _get_or_create_assets(db, cat_by_code):
    for code, names in ASSETS_BY_CATEGORY.items():
        category = cat_by_code[code]
        for name in names:
            exists = (
                await db.execute(
                    select(Asset).where(
                        Asset.name == name, Asset.category_id == category.id
                    )
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(Asset(
                    name=name,
                    category_id=category.id,
                    unit="Nos",
                    is_active=True,
                ))
    await db.flush()


async def _get_or_create_inventory(db, assets, institutions):
    existing_pairs = set(
        (await db.execute(
            select(InventoryItem.asset_id, InventoryItem.institution_id)
        )).all()
    )
    created = []
    for inst in institutions:
        for asset in assets:
            if (asset.id, inst.id) in existing_pairs:
                continue
            total = random.randint(20, 100)
            issued = random.randint(0, total // 2)
            item = InventoryItem(
                asset_id=asset.id,
                institution_id=inst.id,
                quantity_total=total,
                quantity_available=total - issued,
                low_stock_threshold=10,
            )
            db.add(item)
            created.append(item)
    await db.flush()
    return created


async def _ensure_low_stock(db, institutions):
    """Force at least 4 items, across different schools, to be low stock."""
    targets = []
    for inst in institutions[:4]:
        item = (
            await db.execute(
                select(InventoryItem)
                .where(InventoryItem.institution_id == inst.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if item:
            item.quantity_available = random.randint(0, 5)
            if item.quantity_total < item.quantity_available:
                item.quantity_total = item.quantity_available + 10
            targets.append(item)
    await db.flush()
    return targets


async def _generate_movements(db, principal_by_inst, institution_ids):
    existing = (await db.execute(select(func.count(AssetMovement.id)))).scalar() or 0
    if existing > 0:
        return 0

    items = (await db.execute(select(InventoryItem))).scalars().all()
    if not items:
        return 0

    # Build a lookup: (asset_id, institution_id) -> InventoryItem
    item_map = {(i.asset_id, i.institution_id): i for i in items}

    types = [MovementType.ISSUE, MovementType.RETURN, MovementType.TRANSFER]
    now = datetime.utcnow()
    count = 0
    for _ in range(60):
        item = random.choice(items)
        mtype = random.choice(types)
        qty = random.randint(1, 10)
        performed_by = principal_by_inst.get(item.institution_id)
        if not performed_by:
            continue
        created_at = now - timedelta(
            days=random.randint(0, 29),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        movement = AssetMovement(
            inventory_item_id=item.id,
            movement_type=mtype,
            quantity=qty,
            performed_by_id=performed_by,
            created_at=created_at,
        )
        if mtype == MovementType.ISSUE:
            movement.issued_to = random.choice(STUDENT_NAMES)
            movement.notes = "Issued for classroom use"
        elif mtype == MovementType.RETURN:
            movement.notes = "Returned in good condition"
        else:  # TRANSFER — also generate the matching RECEIPT
            others = [i for i in institution_ids if i != item.institution_id]
            if not others:
                movement.movement_type = MovementType.ISSUE
                movement.issued_to = random.choice(STUDENT_NAMES)
                movement.notes = "Issued for classroom use"
            else:
                to_inst = random.choice(others)
                movement.from_institution = item.institution_id
                movement.to_institution = to_inst
                movement.notes = "Inter-school transfer"

                # Create the matching RECEIPT on the destination item
                dest_item = item_map.get((item.asset_id, to_inst))
                if dest_item:
                    db.add(AssetMovement(
                        inventory_item_id=dest_item.id,
                        movement_type=MovementType.RECEIPT,
                        quantity=qty,
                        from_institution=item.institution_id,
                        to_institution=to_inst,
                        performed_by_id=performed_by,
                        notes="Inter-school transfer — received",
                        created_at=created_at,
                    ))
                    count += 1

        db.add(movement)
        count += 1

    await db.flush()
    return count


FIRST_NAMES = [
    "Aarav", "Bhavya", "Chetan", "Divya", "Eshan", "Farhan", "Gagan", "Harsha",
    "Isha", "Jyoti", "Kiran", "Lakshmi", "Manoj", "Nandini", "Pooja", "Rahul",
    "Sahana", "Tejas", "Uma", "Varun", "Yashas", "Zara", "Anita", "Bharath",
]
LAST_NAMES = [
    "Gowda", "Shetty", "Hegde", "Rao", "Patil", "Naik", "Reddy", "Kulkarni",
    "Desai", "Murthy", "Bhat", "Acharya", "Pai", "Kamath", "Nayak",
]
CASTE_CYCLE = [
    CasteCategory.SC, CasteCategory.ST, CasteCategory.OBC,
    CasteCategory.GENERAL, CasteCategory.OBC, CasteCategory.GENERAL,
    CasteCategory.SC, CasteCategory.OBC,
]
SECTIONS = [("9", "A"), ("9", "B"), ("10", "A"), ("10", "B")]


def _recent_weekdays(n: int) -> list[date]:
    out, d = [], date.today()
    while len(out) < n:
        if d.weekday() < 5:  # Mon–Fri
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


async def seed_erp(db) -> dict:
    """Seed School ERP demo data for the pilot school (Rajiv Gandhi HS)."""
    summary = {}
    rgh = (await db.execute(
        select(Institution).where(Institution.code == "RGH-01")
    )).scalar_one_or_none()
    admin = (await db.execute(
        select(User).where(User.email == "admin@kreis.edu")
    )).scalar_one_or_none()
    if not rgh or not admin:
        return summary

    # ── Academic year (single current; reuse if present) ──
    ay = (await db.execute(
        select(AcademicYear).where(
            AcademicYear.institution_id == rgh.id, AcademicYear.is_current.is_(True)
        )
    )).scalars().first()
    if not ay:
        y = date.today().year if date.today().month >= 4 else date.today().year - 1
        ay = AcademicYear(
            institution_id=rgh.id, name=f"{y}-{(y + 1) % 100:02d}",
            start_date=date(y, 4, 1), end_date=date(y + 1, 3, 31), is_current=True,
        )
        db.add(ay)
        await db.flush()

    # ── Class sections ──
    sections = {}
    for grade, sec in SECTIONS:
        cs = (await db.execute(
            select(ClassSection).where(
                ClassSection.institution_id == rgh.id,
                ClassSection.grade == grade, ClassSection.section == sec,
            )
        )).scalars().first()
        if not cs:
            cs = ClassSection(
                institution_id=rgh.id, academic_year_id=ay.id, grade=grade, section=sec
            )
            db.add(cs)
            await db.flush()
        sections[(grade, sec)] = cs

    # ── One teacher per class ──
    teachers = {}
    for grade, sec in SECTIONS:
        email = f"teacher.{grade}{sec.lower()}@rgh.edu"
        t = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if not t:
            t = User(
                email=email, hashed_password=hash_password("School@1234"),
                full_name=f"Teacher {grade}{sec}", role=UserRole.TEACHER,
                institution_id=rgh.id, password_change_required=False,
            )
            db.add(t)
            await db.flush()
        cs = sections[(grade, sec)]
        if cs.class_teacher_id is None:
            cs.class_teacher_id = t.id
        teachers[(grade, sec)] = t

    # ── Subjects (school-wide) ──
    subjects = []
    for nm, cd in [("Mathematics", "MATH"), ("Science", "SCI"), ("English", "ENG")]:
        s = (await db.execute(
            select(Subject).where(Subject.institution_id == rgh.id, Subject.name == nm)
        )).scalars().first()
        if s:
            s.class_section_id = None  # promote to school-wide
        else:
            s = Subject(name=nm, code=cd, institution_id=rgh.id, class_section_id=None)
            db.add(s)
        subjects.append(s)
    await db.flush()

    # ── Students + demographics (20 per class) ──
    created_students = 0
    cidx = 0
    for gi, (grade, sec) in enumerate(SECTIONS):
        cs = sections[(grade, sec)]
        for n in range(1, 21):
            adm = f"RGH-{grade}{sec}-{n:02d}"
            exists = (await db.execute(
                select(Student.id).where(
                    Student.institution_id == rgh.id, Student.admission_number == adm
                )
            )).scalar_one_or_none()
            if exists:
                continue
            gender = Gender.MALE if n % 2 else Gender.FEMALE
            student = Student(
                admission_number=adm, institution_id=rgh.id, class_section_id=cs.id,
                academic_year_id=ay.id,
                full_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                date_of_birth=date(2010 if grade == "10" else 2011, ((n % 12) + 1), ((n % 27) + 1)),
                gender=gender, is_active=True, is_residential=(n % 3 != 0),
            )
            db.add(student)
            await db.flush()
            cc = CASTE_CYCLE[cidx % len(CASTE_CYCLE)]
            cidx += 1
            db.add(StudentDemographics(
                student_id=student.id, caste_category=cc, religion="Hindu",
                father_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                father_phone=f"98{random.randint(10000000, 99999999)}",
                mother_name=f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
                annual_income=random.choice([60000, 90000, 120000, 180000]),
                address_district="Tumkur", address_pin="572101",
            ))
            created_students += 1
    await db.flush()
    summary["students_created"] = created_students

    # ── Attendance: 10 recent weekdays per class ──
    weekdays = _recent_weekdays(10)
    att_created = 0
    for (grade, sec), cs in sections.items():
        students_in = (await db.execute(
            select(Student).where(Student.class_section_id == cs.id, Student.is_active.is_(True))
        )).scalars().all()
        existing = set((await db.execute(
            select(StudentAttendance.student_id, StudentAttendance.date).where(
                StudentAttendance.class_section_id == cs.id,
                StudentAttendance.date >= weekdays[0],
            )
        )).all())
        marker = teachers[(grade, sec)].id
        for st in students_in:
            for d in weekdays:
                if (st.id, d) in existing:
                    continue
                r = random.random()
                status = (
                    StudentAttendanceStatus.ABSENT if r < 0.15
                    else StudentAttendanceStatus.LATE if r < 0.20
                    else StudentAttendanceStatus.PRESENT
                )
                db.add(StudentAttendance(
                    student_id=st.id, class_section_id=cs.id, date=d,
                    status=status, marked_by_id=marker,
                ))
                att_created += 1
    await db.flush()
    summary["attendance_created"] = att_created

    # ── Exams ──
    unit = (await db.execute(
        select(Exam).where(
            Exam.institution_id == rgh.id, Exam.academic_year_id == ay.id,
            Exam.name == "Unit Test 1",
        )
    )).scalars().first()
    if not unit:
        unit = Exam(
            institution_id=rgh.id, academic_year_id=ay.id, name="Unit Test 1",
            exam_type=ExamType.UNIT_TEST,
            start_date=date.today() - timedelta(days=20),
            end_date=date.today() - timedelta(days=16),
        )
        db.add(unit)
        await db.flush()
    midterm = (await db.execute(
        select(Exam).where(
            Exam.institution_id == rgh.id, Exam.academic_year_id == ay.id,
            Exam.name == "Mid-Term",
        )
    )).scalars().first()
    if not midterm:
        midterm = Exam(
            institution_id=rgh.id, academic_year_id=ay.id, name="Mid-Term",
            exam_type=ExamType.MID_TERM,
            start_date=date.today() + timedelta(days=15),
            end_date=date.today() + timedelta(days=20),
        )
        db.add(midterm)
        await db.flush()

    # ── Marks for Unit Test 1 (all students × 3 subjects) ──
    existing_marks = set((await db.execute(
        select(ExamResult.student_id, ExamResult.subject_id).where(
            ExamResult.exam_id == unit.id
        )
    )).all())
    all_students = (await db.execute(
        select(Student).where(Student.institution_id == rgh.id, Student.is_active.is_(True))
    )).scalars().all()
    marks_created = 0
    for st in all_students:
        for subj in subjects:
            if (st.id, subj.id) in existing_marks:
                continue
            obtained = float(random.randint(25, 98))
            pct = obtained / 100 * 100
            db.add(ExamResult(
                student_id=st.id, exam_id=unit.id, subject_id=subj.id,
                marks_obtained=obtained, max_marks=100.0, is_absent=False,
                grade=grade_for(pct),
            ))
            marks_created += 1
    await db.flush()
    summary["marks_created"] = marks_created

    # ── Alumni ──
    alumni_data = [
        (2020, "Prakash Gowda", "10", "Software Engineer", "Infosys", "Bengaluru", "Karnataka"),
        (2021, "Sneha Rao", "10", "Medical Student", "Bangalore Medical College", "Bengaluru", "Karnataka"),
        (2022, "Arjun Patil", "10", "Undergraduate", "IIT Madras", "Chennai", "Tamil Nadu"),
    ]
    alumni_created = 0
    for yr, name, pclass, occ, emp, city, state in alumni_data:
        ex = (await db.execute(
            select(Alumni.id).where(
                Alumni.institution_id == rgh.id, Alumni.full_name == name,
                Alumni.batch_year == yr,
            )
        )).scalar_one_or_none()
        if ex:
            continue
        db.add(Alumni(
            institution_id=rgh.id, full_name=name, batch_year=yr, passed_class=pclass,
            current_occupation=occ, employer=emp, location_city=city, location_state=state,
            phone=f"99{random.randint(10000000, 99999999)}",
            email=f"{name.split()[0].lower()}@example.com",
            updated_by_id=admin.id,
        ))
        alumni_created += 1
    await db.flush()
    summary["alumni_created"] = alumni_created

    # ── Circulars ──
    circ_created = 0
    for title, content, cat, urg, inst in [
        ("Annual Examination Schedule 2026",
         "Mid-term examinations begin in two weeks. Prepare accordingly.",
         CircularCategory.EXAM, Urgency.URGENT, None),
        ("Uniform Distribution Drive",
         "New uniforms will be distributed next month at all residential schools.",
         CircularCategory.ADMINISTRATIVE, Urgency.NORMAL, rgh.id),
    ]:
        ex = (await db.execute(
            select(Circular.id).where(Circular.title == title)
        )).scalar_one_or_none()
        if ex:
            continue
        db.add(Circular(
            institution_id=inst, title=title, content=content, category=cat,
            urgency=urg, uploaded_by_id=admin.id,
        ))
        circ_created += 1
    await db.flush()
    summary["circulars_created"] = circ_created

    # ── Competitive results ──
    comp_created = 0
    comp_specs = [
        (CompetitiveExamName.CET, 2025, 1240, 142.5, True),
        (CompetitiveExamName.JEE_MAINS, 2025, 8800, 96.2, True),
        (CompetitiveExamName.NEET, 2025, 21000, 540.0, True),
    ]
    targets = all_students[:3]
    for st, (ename, yr, rank, score, qual) in zip(targets, comp_specs):
        ex = (await db.execute(
            select(CompetitiveExamResult.id).where(
                CompetitiveExamResult.student_id == st.id,
                CompetitiveExamResult.exam_name == ename,
                CompetitiveExamResult.exam_year == yr,
            )
        )).scalar_one_or_none()
        if ex:
            continue
        db.add(CompetitiveExamResult(
            student_id=st.id, exam_name=ename, exam_year=yr,
            rank=rank, score=score, qualified=qual,
        ))
        comp_created += 1
    await db.flush()
    summary["competitive_created"] = comp_created

    await db.commit()
    return summary


async def seed():
    async with AsyncSessionLocal() as db:
        await _get_or_create_categories(db)
        await _get_or_create_admin(db)
        await _get_or_create_institutions(db)

        institutions = (
            await db.execute(select(Institution).order_by(Institution.id))
        ).scalars().all()
        inst_by_code = {i.code: i for i in institutions}

        await _get_or_create_principals(db, inst_by_code)

        categories = (
            await db.execute(select(AssetCategory))
        ).scalars().all()
        cat_by_code = {c.code: c for c in categories}

        await _get_or_create_assets(db, cat_by_code)

        assets = (await db.execute(select(Asset))).scalars().all()

        await _get_or_create_inventory(db, assets, institutions)
        await _ensure_low_stock(db, institutions)

        principals = (
            await db.execute(
                select(User).where(User.role == UserRole.PRINCIPAL)
            )
        ).scalars().all()
        principal_by_inst = {p.institution_id: p.id for p in principals}

        movement_count = await _generate_movements(
            db, principal_by_inst, [i.id for i in institutions]
        )

        await db.commit()

        erp = await seed_erp(db)

        print("Demo seed complete.")
        print(f"  Institutions: {len(institutions)}")
        print(f"  Assets: {len(assets)}")
        print(f"  Principals: {len(principals)} (password: School@1234)")
        print(f"  Movements generated this run: {movement_count}")
        print("  ── School ERP (Rajiv Gandhi HS) ──")
        print(f"  Students created: {erp.get('students_created', 0)}")
        print(f"  Attendance rows: {erp.get('attendance_created', 0)}")
        print(f"  Marks rows: {erp.get('marks_created', 0)}")
        print(f"  Alumni: {erp.get('alumni_created', 0)}")
        print(f"  Circulars: {erp.get('circulars_created', 0)}")
        print(f"  Competitive results: {erp.get('competitive_created', 0)}")
        print("  Teacher logins: teacher.9a@rgh.edu … (password: School@1234)")
        print("  Admin login: admin@kreis.edu / changeme123")


if __name__ == "__main__":
    asyncio.run(seed())
