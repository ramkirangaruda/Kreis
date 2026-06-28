from app.models.user import User, UserRole
from app.models.institution import Institution
from app.models.asset import Asset, AssetCategory
from app.models.inventory import InventoryItem, AssetMovement, MovementType
from app.models.audit_log import AuditLog

# ── School ERP models ──────────────────────────────────────────
from app.models.student import (
    AcademicYear,
    ClassSection,
    Student,
    StudentDemographics,
    StudentHealthRecord,
    SickBayVisit,
    Gender,
    CasteCategory,
)
from app.models.academic import (
    Subject,
    Exam,
    ExamResult,
    CompetitiveExamResult,
    TimetableSlot,
    ExamType,
    CompetitiveExamName,
    DayOfWeek,
)
from app.models.attendance import (
    StudentAttendance,
    FacultyAttendance,
    StudentAttendanceStatus,
    FacultyAttendanceStatus,
    LeaveType,
)
from app.models.document import (
    Circular,
    CircularAcknowledgement,
    Memo,
    UploadedDocument,
    UtilityBill,
    ScannerDevice,
    AttendanceRollup,
    CircularCategory,
    Urgency,
    RecipientType,
    DocType,
    OcrStatus,
    BillType,
)
from app.models.alumni import Alumni
