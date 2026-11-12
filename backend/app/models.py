import uuid
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Numeric, Text, UniqueConstraint, Table, Column, Integer, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def uid():
    return str(uuid.uuid4())

role_permissions = Table(
    "role_permissions", Base.metadata,
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", String(36), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)
user_roles = Table(
    "user_roles", Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", String(36), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)
organization_roles = Table(
    "organization_roles", Base.metadata,
    Column("organization_id", String(36), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
    Column("role", String(50), primary_key=True),
)


employee_org_units = Table(
    "employee_org_units", Base.metadata,
    Column("employee_id", String(36), ForeignKey("employees.id", ondelete="CASCADE"), primary_key=True),
    Column("org_unit_id", String(36), ForeignKey("organizational_units.id", ondelete="CASCADE"), primary_key=True),
)

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

class Person(Base, TimestampMixin):
    __tablename__ = "people"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str|None] = mapped_column(String(50), nullable=True)
    email: Mapped[str|None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class OrganizationalUnit(Base, TimestampMixin):
    __tablename__ = "organizational_units"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name_el: Mapped[str] = mapped_column(String(150))
    name_en: Mapped[str|None] = mapped_column(String(150), nullable=True)
    parent_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    position: Mapped[str|None] = mapped_column(String(150), nullable=True)
    profile: Mapped[str|None] = mapped_column(String(20), nullable=True)  # PRODUCTION | SUPPORT | MANAGEMENT | None = δεν έχει οριστεί
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id"), unique=True)
    employee_code: Mapped[str] = mapped_column(String(50), unique=True)
    default_org_unit_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrgUnitPosition(Base, TimestampMixin):
    __tablename__ = "org_unit_positions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizational_units.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("org_unit_id", "name", name="uq_org_unit_position"),)


class ProductionWorkEntry(Base, TimestampMixin):
    __tablename__ = "production_work_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    org_unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizational_units.id"), index=True)
    employee_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("employees.id"), nullable=True, index=True)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), index=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    supplier_group: Mapped[str] = mapped_column(String(30), default="OTHER")
    source: Mapped[str] = mapped_column(String(30), default="WINDOWS")
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    transfer_id: Mapped[str|None] = mapped_column(String(36), nullable=True, index=True)  # Android: ποια μεταφορά υλικού δημιούργησε την καταχώρηση (για αναίρεση/διόρθωση)


class ProductionAttendance(Base, TimestampMixin):
    __tablename__ = "production_attendance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), index=True)
    status: Mapped[str|None] = mapped_column(String(10), nullable=True)  # PRESENT|ABSENT|LEFT
    org_unit_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    position_text: Mapped[str|None] = mapped_column(String(150), nullable=True)  # free text until OrgUnitPosition data is ready
    since_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)  # πότε ήρθε (μόνο αν άργησε/ξαναήρθε)
    late: Mapped[bool] = mapped_column(Boolean, default=False)  # ΑΡΓΟΠΟΡΙΑ = παρών με άφιξη μετά την έναρξη βάρδιας
    # Ολιγόωρες απουσίες της ημέρας: JSON λίστα [{"from":"ΩΩ:ΛΛ","to":"ΩΩ:ΛΛ"|null}] (τοπική ώρα)· ανεξάρτητες από την κατάσταση (Παρών/Αργοπορία/Έφυγε)
    short_leaves: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    __table_args__ = (UniqueConstraint("work_date", "employee_id", name="uq_production_attendance_day_emp"),)


class ProductionAttendanceEvent(Base):
    """Ιστορικό αλλαγών παρουσίας/τμήματος (εργαζόμενος, νέα κατάσταση, προηγούμενη κατάσταση, ώρα, χρήστης).
    Τροφοδοτείται από το PUT /production/attendance (Android + Windows) -- μία κοινή αποθήκευση. Επιτρέπει
    ΑΚΥΡΩΣΗ της τελευταίας αλλαγής ενός εργαζομένου (επαναφέρει την προηγούμενη κατάσταση και τα διαστήματα του σημείου 2)."""
    __tablename__ = "production_attendance_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), index=True)
    user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    status: Mapped[str|None] = mapped_column(String(10), nullable=True)
    org_unit_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    since_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    prev_exists: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_status: Mapped[str|None] = mapped_column(String(10), nullable=True)
    prev_org_unit_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    prev_since_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_late: Mapped[bool] = mapped_column(Boolean, default=False)
    prev_arrived_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_interval_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    opened_interval_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    unit_ids: Mapped[str|None] = mapped_column(Text, nullable=True)  # JSON: σύνολο τμημάτων του εργαζομένου μετά την αλλαγή
    prev_unit_ids: Mapped[str|None] = mapped_column(Text, nullable=True)  # JSON: σύνολο πριν την αλλαγή (για ΑΚΥΡΩΣΗ)


class ProductionPlacementInterval(Base, TimestampMixin):
    """Append-only log of which department an employee was in and when -- purely additive, never
    read by the existing production reports (ανά ΑΗΗΕ / ανά Τμήμα-Άτομο / Δελτίο Παραγωγής), so their
    numbers never change. One open row (ended_at=None) per employee at a time; a new placement closes
    the previous open row and opens a new one. Fed by every place an employee's current department
    changes "today": the permanent ΕΡΓΑΤΕΣ roster (_replace_employee_units) and the daily Δελτίο
    Παρουσίας (production_attendance)."""
    __tablename__ = "production_placement_intervals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    employee_id: Mapped[str] = mapped_column(String(36), ForeignKey("employees.id"), index=True)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    org_unit_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    org_unit_ids: Mapped[str|None] = mapped_column(Text, nullable=True)  # JSON: λίστα ΟΛΩΝ των τμημάτων του εργαζομένου στο διάστημα

class MaterialOutputEntry(Base, TimestampMixin):
    __tablename__ = "material_output_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category_group: Mapped[str] = mapped_column(String(30), index=True)
    material_label: Mapped[str] = mapped_column(String(150), index=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    source: Mapped[str] = mapped_column(String(30), default="WINDOWS")
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class MaterialShipmentEntry(Base, TimestampMixin):
    """Shipments/sales of already-processed Υλικά (mirrors MaterialOutputEntry's shape so the two
    subtract cleanly per material_label+category_group). First source: dispatch-note types 2000/7000
    of the company's own sales-control export, matched to material names only (kg + date) -- ERP
    document/client fields from that source are intentionally not carried in yet, per user request."""
    __tablename__ = "material_shipment_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category_group: Mapped[str] = mapped_column(String(30), index=True)
    material_label: Mapped[str] = mapped_column(String(150), index=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    source: Mapped[str] = mapped_column(String(30), default="WINDOWS")
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ShipmentHistoryEntry(Base, TimestampMixin):
    """Row-per-delivery-note historical record from the company's official 2026 ΔΑ (Δελτίο
    Αποστολής) log -- richer than MaterialShipmentEntry's aggregate rows (ΔΑ number, weighbridge,
    transporter, recipient, EKA/REPTOOL codes) but NOT a replacement for it: this is a read-only
    traceability/history list shown under Φορτώσεις, independent of the live LoadingOrder lot
    workflow (which has no real historical lot data to attach these to). kind distinguishes plain
    material sales/shipments ('MATERIAL', sheet 'Δ.Α.') from ΑΗΗΕ-category shipments to other
    licensed units ('WEEE_TO_UNIT', sheet 'Δ.Α. (ΛΕΥΚΕΣ)')."""
    __tablename__ = "shipment_history_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    da_number: Mapped[str|None] = mapped_column(String(40), nullable=True, index=True)
    weighbridge_number: Mapped[str|None] = mapped_column(String(80), nullable=True)
    transporter: Mapped[str|None] = mapped_column(String(200), nullable=True)
    recipient: Mapped[str|None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(String(200))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    eka_code: Mapped[str|None] = mapped_column(String(40), nullable=True)
    reptool_code: Mapped[str|None] = mapped_column(String(60), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(30), default="DA_LOG_2026")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Στοιχεία δελτίου για Ζ(i)/Ζ(ii) (ίδια τιμή σε όλες τις γραμμές ενός Δ.Α.)
    first_recipient: Mapped[str|None] = mapped_column(String(200), nullable=True)
    mgmt_operation: Mapped[str|None] = mapped_column(String(40), nullable=True)
    tracking_document: Mapped[str|None] = mapped_column(String(120), nullable=True)
    destination_country: Mapped[str|None] = mapped_column(String(80), nullable=True)
    container_number: Mapped[str|None] = mapped_column(String(120), nullable=True)
    gr_notification_no: Mapped[str|None] = mapped_column(String(120), nullable=True)
    bill_of_lading: Mapped[str|None] = mapped_column(String(120), nullable=True)
    # Φόρμα Δ.Α. (K3/K4): στοιχεία δελτίου ίδια σε όλες τις γραμμές ενός Δ.Α. + ακύρωση (ακυρωμένο: active=False, cancelled_at συμπληρωμένο)
    vehicle_registration: Mapped[str|None] = mapped_column(String(40), nullable=True)
    dispatch_reason: Mapped[str|None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    customer_address: Mapped[str|None] = mapped_column(String(300), nullable=True)
    cancelled_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str|None] = mapped_column(String(36), nullable=True)

class PressOpeningStock(Base, TimestampMixin):
    """Αρχικό απόθεμα ΜΠΑΛΩΝ της πρέσας (31/12/2025) ανά στήλη πρέσας: μόνο για την καρτέλα «Πρέσα»· ΔΕΝ μετράει στο απόθεμα των υλικών (υποσύνολό τους)."""
    __tablename__ = "press_opening_stocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    press_group: Mapped[str] = mapped_column(String(100), unique=True, index=True)   # όπως το material_group των bale_entries
    bales: Mapped[int] = mapped_column(Integer, default=0)
    kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    as_of_date: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)

class InventoryYearCorrection(Base, TimestampMixin):
    """Απογραφή › Αποθέματα: διορθωμένο απόθεμα 31-12 ενός έτους ανά ΑΗΗΕ κωδικό / υλικό. Για το 2025 το «applied_*» (διορθωμένο − απόθεμα εφαρμογής) προστίθεται στο αρχικό απόθεμα 1/1/2026
    (WEEE: επικάλυψη του JSON· MAT/PRESS: στη γραμμή target των πινάκων αρχικού αποθέματος)· διαγραφή της τιμής αφαιρεί ακριβώς όσο είχε προστεθεί."""
    __tablename__ = "inventory_year_corrections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(10), index=True)      # WEEE | MAT | PRESS | COMM
    year: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(200), index=True)      # κωδικός ΑΗΗΕ ή κλειδί στήλης υλικού
    target: Mapped[str|None] = mapped_column(String(200), nullable=True)   # ετικέτα/κωδικός της γραμμής αρχικού αποθέματος που αλλάζει
    kg: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    pieces: Mapped[int|None] = mapped_column(Integer, nullable=True)
    applied_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    applied_pieces: Mapped[int] = mapped_column(Integer, default=0)

class MaterialLayoutSnapshot(Base, TimestampMixin):
    """Καρτέλες Υλικών ανά ΜΗΝΑ: αποθηκευμένη διάταξη (ομαδοποίηση/σειρά) παλιότερου μήνα. Ο τρέχων μήνας ζει στους κανονικούς πίνακες. Αλλάζει ΜΟΝΟ η εμφάνιση (ποτέ απόθεμα/κινήσεις)."""
    __tablename__ = "material_layout_snapshots"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)     # YYYY-MM
    payload: Mapped[str] = mapped_column(Text)


class MaterialOpeningStock(Base, TimestampMixin):
    """A documented, point-in-time physical stock count for materials (e.g. 31/12/2025),
    read from the real inventory sheet -- never invented. reptool_code/her_description are
    filled in only when the material_label could be matched against the Materials registry;
    left null otherwise so the gap stays visible instead of silently guessed."""
    __tablename__ = "material_opening_stocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    as_of_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category_group: Mapped[str] = mapped_column(String(30), index=True)
    material_label: Mapped[str] = mapped_column(String(150), index=True)
    kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    pieces: Mapped[int|None] = mapped_column(Integer, nullable=True, default=0)    # τεμάχια αρχικού αποθέματος (M2)
    reptool_code: Mapped[str|None] = mapped_column(String(60), nullable=True, index=True)
    her_description: Mapped[str|None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="WINDOWS")
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class BaleEntry(Base, TimestampMixin):
    """Per-bale packaging detail from the ΠΡΕΣΑ (baling press) workbook's '6 (ΠΡΕΣΑ)' / 'ΜΠΑΛΕΣ'
    sheets. Purely informational: these materials are already counted in MaterialOutputEntry
    (καρτέλες 3-5), so this table is never summed into any existing total -- it only shows the
    bale-level breakdown (count + kg per bale) for the ΠΡΕΣΑ tab. bale_seq is the Α/Α sequence
    number within material_group+period, one row per physical bale; null for is_bulk rows, used
    for two cases where no per-bale breakdown exists in the source sheet: (1) an aggregate row
    covering several bales as one total (bale_count holds how many, e.g. ΣΕΡΠΑΤΙΝΑ/ΧΑΛΚΟΣ/
    ΚΑΛΩΔΙΑ/ΧΑΡΤΙ/ΝΑΫΛΟΝ/ΠΟΛΥΟΥΡΕΘΑΝΗ/ΑΛΟΥΜΙΝΙΟ ΜΑΛΑΚΟ, which the source only totals, never
    lists bale-by-bale), and (2) material tracked ΧΥΜΑ/unbaled (bulk ΣΙΔΗΡΟΣ) where bale_count
    stays null since there are no bales at all, only a bulk kg figure."""
    __tablename__ = "bale_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    period: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    material_group: Mapped[str] = mapped_column(String(100), index=True)
    bale_seq: Mapped[int|None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    is_bulk: Mapped[bool] = mapped_column(Boolean, default=False)
    bale_count: Mapped[int|None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="WINDOWS")
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str|None] = mapped_column(String(255), nullable=True)

class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name_el: Mapped[str] = mapped_column(String(100))
    permissions = relationship("Permission", secondary=role_permissions, lazy="selectin")

class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    person_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("people.id"), nullable=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    pin_hash: Mapped[str|None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    roles = relationship("Role", secondary=user_roles, lazy="selectin")

class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str|None] = mapped_column(String(200), nullable=True)
    tax_id: Mapped[str|None] = mapped_column(String(30), nullable=True, index=True)
    email: Mapped[str|None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str|None] = mapped_column(String(50), nullable=True)
    galaxy_id: Mapped[str|None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    supplier_kind: Mapped[str|None] = mapped_column(String(20), nullable=True)
    # PICKUP_POINT: όταν είναι αποστολέας στη ζωντανή ροή, προμηθευτής της παραλαβής είναι το σημείο παραλαβής
    supplier_source: Mapped[str|None] = mapped_column(String(20), nullable=True)
    # Άδεια (συλλέκτη μεταφορέα / αποδέκτη) και ΑΔΑ της άδειας -- για τις προβολές Ζ(i)/Ζ(ii) του Ιστορικού Δελτίων Αποστολής
    permit_number: Mapped[str|None] = mapped_column(String(100), nullable=True)
    permit_ada: Mapped[str|None] = mapped_column(String(100), nullable=True)


class OrganizationRegistryDetail(Base, TimestampMixin):
    __tablename__ = "organization_registry_details"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, index=True)
    external_code: Mapped[str|None] = mapped_column(String(50), nullable=True, index=True)
    phone2: Mapped[str|None] = mapped_column(String(50), nullable=True)
    street: Mapped[str|None] = mapped_column(String(250), nullable=True)
    street_number: Mapped[str|None] = mapped_column(String(50), nullable=True)
    municipality: Mapped[str|None] = mapped_column(String(150), nullable=True)
    prefecture: Mapped[str|None] = mapped_column(String(150), nullable=True)
    country_code: Mapped[str|None] = mapped_column(String(10), nullable=True)
    profession: Mapped[str|None] = mapped_column(String(250), nullable=True)
    transaction_code: Mapped[str|None] = mapped_column(String(50), nullable=True, index=True)

class SupplierBranch(Base, TimestampMixin):
    __tablename__ = "supplier_branches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(500), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("supplier_id","name",name="uq_supplier_branch"),)

class CarrierDriver(Base, TimestampMixin):
    __tablename__ = "carrier_drivers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    carrier_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    phone: Mapped[str|None] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class CarrierVehicle(Base, TimestampMixin):
    __tablename__ = "carrier_vehicles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    carrier_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    plate_number: Mapped[str] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("carrier_id","plate_number",name="uq_carrier_vehicle"),)

class VisitorLog(Base, TimestampMixin):
    __tablename__ = "visitor_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    visit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    arrival_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    departure_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String(250))
    source_type: Mapped[str] = mapped_column(String(40), default="MANUAL", index=True)
    source_id: Mapped[str|None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

class WEEECategory(Base, TimestampMixin):
    __tablename__ = "weee_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    description_el: Mapped[str] = mapped_column(String(300))
    parent_code: Mapped[str|None] = mapped_column(String(30), nullable=True)
    is_internal_subcategory: Mapped[bool] = mapped_column(Boolean, default=False)
    average_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    her_description: Mapped[str|None] = mapped_column(String(300), nullable=True)
    eka_code: Mapped[str|None] = mapped_column(String(50), nullable=True)
    processable: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int|None] = mapped_column(Integer, nullable=True)   # σειρά των δικών μας υποκατηγοριών μέσα στην ΑΗΗΕ-γονέα (Windows και Android)

class Material(Base, TimestampMixin):
    __tablename__ = "materials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    internal_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    internal_name: Mapped[str] = mapped_column(String(250))
    galaxy_code: Mapped[str|None] = mapped_column(String(50), nullable=True, index=True)
    galaxy_description: Mapped[str|None] = mapped_column(String(250), nullable=True)
    genre: Mapped[str|None] = mapped_column(String(120), nullable=True)
    official_description: Mapped[str|None] = mapped_column(String(300), nullable=True)
    her_description: Mapped[str|None] = mapped_column(String(300), nullable=True)
    eka_code: Mapped[str|None] = mapped_column(String(50), nullable=True)
    reptool_code: Mapped[str|None] = mapped_column(String(100), nullable=True)
    reptool_description: Mapped[str|None] = mapped_column(String(500), nullable=True)
    is_precious: Mapped[bool] = mapped_column(Boolean, default=False)
    export_step_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=Decimal("0.500"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    short_description: Mapped[str|None] = mapped_column(String(300), nullable=True)   # Σύντομη περιγραφή (προαιρετική)· κενή = εμφανίζεται η επίσημη
    is_umbrella: Mapped[bool] = mapped_column(Boolean, default=False)                  # «Κάτω από αυτό το υλικό ομαδοποιούνται υποπροϊόντα» (π.χ. 00195 Ημιέτοιμο - Χύδην)
    label_group: Mapped[str|None] = mapped_column(String(120), nullable=True, index=True)   # «Αυτό το υλικό ομαδοποιείται σε μια ετικέτα» (π.χ. ΠΛΑΣΤΙΚΑ ΜΕΡΗ)
    label_group_order: Mapped[int] = mapped_column(Integer, default=0)
    is_commercial: Mapped[bool] = mapped_column(Boolean, default=False)                # Εμπορικό υλικό: αγοράζεται από την εταιρεία, δεν μετρά σε απογραφή/ισοζύγια, φαίνεται μόνο στην Αποθήκη και στην καρτέλα «Εμπορικά»
    can_bale: Mapped[bool] = mapped_column(Boolean, default=False)                    # Μπορεί να γίνει μπάλα (εμφανίζει «Μπάλα» στην εξαγωγή Android)
    press_label: Mapped[str|None] = mapped_column(String(100), nullable=True)           # Όνομα στήλης στην Πρέσα (αν διαφέρει από το όνομα υλικού)
    storage_group_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("storage_groups.id"), nullable=True, index=True)  # «Ομάδα αποθήκης» (προαιρετικό)

class StorageGroup(Base, TimestampMixin):
    """Ομάδες αποθήκης σε δύο επίπεδα: Κατηγορία (parent_id = None, π.χ. Μέταλλα) και Ομάδα μέσα σε αυτήν (π.χ. Χαλκός).
    Κάθε υλικό ανήκει σε ΜΙΑ ομάδα (Material.storage_group_id)."""
    __tablename__ = "storage_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(150))
    parent_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("storage_groups.id"), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class CollectionMediumType(Base, TimestampMixin):
    __tablename__ = "collection_medium_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name_el: Mapped[str] = mapped_column(String(100))
    default_tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    requires_unique_number: Mapped[bool] = mapped_column(Boolean, default=False)
    never_reuse_number: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Χρήση είδους: IN = εισερχόμενο (παραλαβές), OUT = εξερχόμενο (ταξινόμηση εξόδου), BOTH = και τα δύο
    usage: Mapped[str] = mapped_column(String(10), default="BOTH", server_default="BOTH")
    # Σταθερό αποβαρό: όλα τα μέσα του τύπου έχουν το default_tare_weight του τύπου (δεν υπάρχει αποβαρό ανά μέσο)
    tare_fixed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Σύντομος κωδικός τύπου (3 χαρακτήρες) για τους αυτόματους κωδικούς μέσων: ΕΕ-ΤΤΤ-ΝΝΝΝ (π.χ. 26-PAL-0001)
    short_code: Mapped[str|None] = mapped_column(String(3), nullable=True)
    # Μέσο μίας χρήσης (σάκος, μεγασάκος…): ο κωδικός δίνεται στην πρώτη χρήση, όχι στη δημιουργία στα Μητρώα
    single_use: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

class CodeCounter(Base):
    """ΕΝΑΣ μετρητής ανά (έτος, 3χαρακτήρης κωδικός): κοινός για τους κωδικούς τύπων και τους κωδικούς περιεχομένου και για όλες τις πηγές.
    Δεν μειώνεται ποτέ· το (έτος, κωδικός) είναι μοναδικό από τη βάση."""
    __tablename__ = "code_counters"
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer, default=0)

class ContentCode(Base):
    """Κωδικοί περιεχομένου (για μέσα μίας χρήσης)· δεν επιτρέπεται να ισούνται με κωδικό τύπου μέσου."""
    __tablename__ = "content_codes"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    source: Mapped[str|None] = mapped_column(String(30), nullable=True)

class ContentCodeMap(Base):
    """Αντιστοίχιση περιεχομένου -> κωδικός περιεχομένου: kind='WEEE' (key = επίσημος κωδικός κατηγορίας ΑΗΗΕ) ή 'SGROUP' (key = όνομα κατηγορίας αποθήκης υλικών)."""
    __tablename__ = "content_code_map"
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    code: Mapped[str] = mapped_column(String(3), ForeignKey("content_codes.code"))

class MediumCodeCounter(Base):
    """Μετρητής αυτόματων κωδικών ανά τύπο και έτος· δεν μειώνεται ποτέ (δεν επαναχρησιμοποιούνται αριθμοί)."""
    __tablename__ = "medium_code_counters"
    type_id: Mapped[str] = mapped_column(String(36), ForeignKey("collection_medium_types.id"), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_no: Mapped[int] = mapped_column(Integer, default=0)

class CollectionMedium(Base, TimestampMixin):
    __tablename__ = "collection_media"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    type_id: Mapped[str] = mapped_column(String(36), ForeignKey("collection_medium_types.id"))
    code: Mapped[str] = mapped_column(String(80), index=True)
    tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    linked_loading_order_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("loading_orders.id"), nullable=True)
    # Κλειστό μέσο: έχει κιλά και ΔΕΝ δέχεται άλλα (δεν προσφέρεται στην Ταξινόμηση, ο server απορρίπτει νέα κιλά). Πηγαίνει κανονικά στην παραγωγή.
    # Γίνεται πάλι ανοιχτό όταν αδειάσει (_medium_release). Ανοιχτό = False (προεπιλογή, και για όλα τα υπάρχοντα μέσα).
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Ο κωδικός είναι μοναδικός ΜΕΣΑ στον τύπο· ο ίδιος κωδικός επιτρέπεται σε άλλον τύπο (το εσωτερικό id είναι το κλειδί).
    __table_args__ = (UniqueConstraint("type_id","code",name="uq_collection_media_type_code"),)

class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String(150), unique=True)
    value: Mapped[str] = mapped_column(Text)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    old_values: Mapped[str|None] = mapped_column(Text, nullable=True)
    new_values: Mapped[str|None] = mapped_column(Text, nullable=True)
    reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class ContainerAsset(Base, TimestampMixin):
    __tablename__ = "containers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    container_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_organization_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    tare_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)

class InboundTrip(Base, TimestampMixin):
    __tablename__ = "inbound_trips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    receipt_number: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    receipt_type: Mapped[str] = mapped_column(String(40), index=True)
    receipt_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    carrier_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    driver_name: Mapped[str|None] = mapped_column(String(200), nullable=True)
    vehicle_registration: Mapped[str|None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    created_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    aggregate_weighbridge_number: Mapped[str|None] = mapped_column(String(100), nullable=True)
    deleted_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    cancelled_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)   # Ακυρώθηκε (μένει στο ιστορικό· δεν μετράει σε σύνολα/αποθέματα, όπως η διαγραφή)
    cancel_reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str|None] = mapped_column(String(36), nullable=True)
    cancel_snapshot: Mapped[str|None] = mapped_column(Text, nullable=True)   # JSON: μερίδια αποθέματος + κινήσεις πριν την ακύρωση (για ακριβή επαναφορά με Αναίρεση)

class InboundLoad(Base, TimestampMixin):
    __tablename__ = "inbound_loads"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    trip_id: Mapped[str] = mapped_column(String(36), ForeignKey("inbound_trips.id", ondelete="CASCADE"), index=True)
    load_sequence: Mapped[int] = mapped_column(default=1)
    supplier_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    order_number: Mapped[str|None] = mapped_column(String(100), nullable=True, index=True)
    incoming_container_number: Mapped[str|None] = mapped_column(String(80), nullable=True)
    incoming_container_tare: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    outgoing_container_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("containers.id"), nullable=True)
    outgoing_container_tare: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    gross_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    net_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    ready_for_sorting_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    dpp_number: Mapped[int|None] = mapped_column(Integer, nullable=True, index=True)
    weighbridge_number: Mapped[str|None] = mapped_column(String(100), nullable=True)
    dispatch_note_number: Mapped[str|None] = mapped_column(String(100), nullable=True)
    seal_number: Mapped[str|None] = mapped_column(String(100), nullable=True)
    __table_args__ = (UniqueConstraint("trip_id", "load_sequence", name="uq_trip_load_sequence"),)

class SortingSession(Base, TimestampMixin):
    __tablename__ = "sorting_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    inbound_load_id: Mapped[str] = mapped_column(String(36), ForeignKey("inbound_loads.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="NOT_STARTED", index=True)
    correction: Mapped[bool] = mapped_column(Boolean, default=False)  # επιστράφηκε από τα Windows για διόρθωση ("Προς Διόρθωση") μέχρι να ξαναολοκληρωθεί από το Android
    started_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    sorting_confirmed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    sorting_confirmed_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    logistics_confirmed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    logistics_confirmed_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    management_confirmed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    management_confirmed_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    requires_management_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    final_sorting_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    final_difference: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    foreign_materials: Mapped[str|None] = mapped_column(String(200), nullable=True)
    foreign_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    special_waste: Mapped[str|None] = mapped_column(String(200), nullable=True)
    special_waste_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    load_pure: Mapped[bool] = mapped_column(Boolean, default=False)
    check_special: Mapped[bool] = mapped_column(Boolean, default=False)
    check_kday: Mapped[bool] = mapped_column(Boolean, default=False)
    check_non_integer: Mapped[bool] = mapped_column(Boolean, default=False)

class SortingEntry(Base, TimestampMixin):
    __tablename__ = "sorting_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sorting_sessions.id", ondelete="CASCADE"), index=True)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), index=True)
    collection_medium_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("collection_media.id"), nullable=True, index=True)
    entry_type: Mapped[str] = mapped_column(String(30), default="MEDIUM")
    raw_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    approved_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    piece_count: Mapped[int|None] = mapped_column(nullable=True)
    created_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    # Προέλευση της καταχώρησης: 'PC' (Windows) ή 'ANDROID'· NULL = παλαιότερη καταχώρηση χωρίς γνωστή προέλευση (δεν δείχνει εικονίδιο)
    source: Mapped[str|None] = mapped_column(String(10), nullable=True)

class SortingAdjustment(Base):
    __tablename__ = "sorting_adjustments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sorting_entry_id: Mapped[str] = mapped_column(String(36), ForeignKey("sorting_entries.id", ondelete="CASCADE"), index=True)
    old_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    new_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class FileAttachment(Base):
    __tablename__ = "file_attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    category: Mapped[str] = mapped_column(String(50), default="GENERAL")
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str|None] = mapped_column(String(120), nullable=True)
    uploaded_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


# ---- Build 0.6: WEEE warehouse and production dispatch ----
class InventoryLocation(Base, TimestampMixin):
    __tablename__ = "inventory_locations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name_el: Mapped[str] = mapped_column(String(150))
    domain: Mapped[str] = mapped_column(String(50), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class WEEEStockLot(Base, TimestampMixin):
    __tablename__ = "weee_stock_lots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_sorting_entry_id: Mapped[str] = mapped_column(String(36), ForeignKey("sorting_entries.id"), unique=True, index=True)
    inbound_load_id: Mapped[str] = mapped_column(String(36), ForeignKey("inbound_loads.id"), index=True)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), index=True)
    collection_medium_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("collection_media.id"), nullable=True, index=True)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_locations.id"), index=True)
    original_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    available_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    piece_count: Mapped[int|None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE", index=True)

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    domain: Mapped[str] = mapped_column(String(50), index=True)
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_stock_lots.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(50), index=True)
    from_location_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("inventory_locations.id"), nullable=True)
    to_location_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("inventory_locations.id"), nullable=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    org_unit_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    transfer_id: Mapped[str|None] = mapped_column(String(36), nullable=True, index=True)  # μεταφορά προς παραγωγή που δημιούργησε την κίνηση (για να μην μετράει διπλά με την εγγραφή παραγωγής)

class ProductionTransfer(Base, TimestampMixin):
    __tablename__ = "production_transfers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    transfer_number: Mapped[str] = mapped_column(String(70), unique=True, index=True)
    destination_org_unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizational_units.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="CONFIRMED", index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    present_json: Mapped[str|None] = mapped_column(Text, nullable=True)   # στιγμιότυπο παρόντων στο τμήμα (για μελλοντικές αναφορές παραγωγικότητας)

class IdempotencyKey(Base):
    """Μοναδικός κωδικός αιτήματος εγγραφής (header X-Request-Id): αν το ίδιο αίτημα ξαναέρθει (επανάληψη από την ουρά της οθόνης),
    ο server απαντά με την ΑΡΧΙΚΗ απάντηση χωρίς να γράψει ξανά."""
    __tablename__ = "idempotency_keys"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column()
    body: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

class ProductionTransferItem(Base):
    __tablename__ = "production_transfer_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    transfer_id: Mapped[str] = mapped_column(String(36), ForeignKey("production_transfers.id", ondelete="CASCADE"), index=True)
    stock_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_stock_lots.id"), index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    # Υπόλοιπο μέσου: το απόβαρο ΜΕΝΕΙ αυτό της στιγμής της αποστολής· weight = καθαρή παραγωγή (στάλθηκαν − υπόλοιπο)
    tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    sent_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    remainder_net: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    remainder_gross: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    remainder_mode: Mapped[str|None] = mapped_column(String(10), nullable=True)
    remainder_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    emptied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    remainder_present: Mapped[str|None] = mapped_column(Text, nullable=True)   # στιγμιότυπο παρόντων τη στιγμή του υπολοίπου


# ---- Build 0.7: Production daily balances and outputs ----
class ProductionInputBalance(Base, TimestampMixin):
    __tablename__ = "production_input_balances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    transfer_item_id: Mapped[str] = mapped_column(String(36), ForeignKey("production_transfer_items.id"), unique=True, index=True)
    org_unit_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizational_units.id"), index=True)
    initial_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    current_remaining_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    status: Mapped[str] = mapped_column(String(40), default="OPEN", index=True)

class ProductionRemainderSnapshot(Base):
    __tablename__ = "production_remainder_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    balance_id: Mapped[str] = mapped_column(String(36), ForeignKey("production_input_balances.id"), index=True)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    previous_remaining_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    remaining_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    processed_since_previous: Mapped[Decimal] = mapped_column(Numeric(14,3))
    recorded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)

class ReadyMaterialLot(Base, TimestampMixin):
    __tablename__ = "ready_material_lots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    lot_number: Mapped[str] = mapped_column(String(90), unique=True, index=True)
    material_id: Mapped[str] = mapped_column(String(36), ForeignKey("materials.id"), index=True)
    output_form: Mapped[str] = mapped_column(String(40), index=True)
    collection_medium_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("collection_media.id"), nullable=True, index=True)
    gross_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    net_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    original_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)   # αρχικό βάρος εξαγωγής (δεν αλλάζει με τις μερικές φορτώσεις· το net_weight είναι το υπόλοιπο)
    location_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_locations.id"), index=True)
    source_org_unit_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizational_units.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE", index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    # Android ΥΛΙΚΑ → Εξαγωγή: τύπος εγγραφής, περίοδος (για ισοζύγια μάζας), καταμετρούμενα κιλά περιόδου, ετικέτα DEMO
    entry_type: Mapped[str] = mapped_column(String(20), default="EXPORT")          # EXPORT | INVENTORY
    period_year: Mapped[int|None] = mapped_column(Integer, nullable=True, index=True)
    period_quarter: Mapped[int|None] = mapped_column(Integer, nullable=True)
    period_month: Mapped[int|None] = mapped_column(Integer, nullable=True)
    counted_kg: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)   # τα κιλά που καταμετρώνται στην περίοδο (≠ φυσικό βάρος όταν η εξαγωγή γίνεται από μέσο απογραφής)
    storage_group_id: Mapped[str|None] = mapped_column(String(36), nullable=True)    # κατηγορία αποθήκης την ώρα της εξαγωγής
    source_inventory_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sub_label: Mapped[str|None] = mapped_column(String(200), nullable=True)            # υποπροϊόν ομάδας (BULK_SUB) στο οποίο καταχωρήθηκε η εξαγωγή· κενό = εξαγωγή του ίδιου του υλικού (Parent)
    is_bale: Mapped[bool] = mapped_column(Boolean, default=False)                       # εξαγωγή παλέτας ως ΜΠΑΛΑ (μετράει μία φορά στο απόθεμα)

class MaterialLabelMap(Base, TimestampMixin):
    """ΜΟΝΙΜΗ αντιστοίχιση ετικέτας Excel (στήλη καρτέλας Υλικών ή στήλης Πρέσας) → υλικό των Μητρώων, ώστε κάθε νέο Excel να αναγνωρίζεται.
    kind: MATERIAL (η ετικέτα είναι το υλικό material_id) · BULK_SUB (υποκατηγορία χύδην· πηγαίνει στο υλικό-ομπρέλα material_id, π.χ. 00195) ·
    RECEIPTS (στήλη «από παραλαβές»· συνδέεται με κατηγορία ΑΗΗΕ weee_category_id, μόνο ανάγνωση) · SUM (η ετικέτα είναι το άθροισμα των μελών της ομάδας group_name) · NONE (δεν είναι υλικό).
    Μία ετικέτα (ανά πηγή) έχει ένα υλικό· ένα υλικό μπορεί να έχει πολλές ετικέτες. Για BULK_SUB: active/sort_order ορίζουν ενεργή/μη ενεργή υποκατηγορία και σειρά."""
    __tablename__ = "material_label_maps"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source: Mapped[str] = mapped_column(String(10), default="EXCEL")            # EXCEL | PRESS
    label: Mapped[str] = mapped_column(String(200))
    label_key: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="MATERIAL")
    material_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("materials.id"), nullable=True, index=True)
    weee_category_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    group_name: Mapped[str|None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    sheet: Mapped[str|None] = mapped_column(String(30), nullable=True)           # καρτέλα του προγράμματος που όρισε ο χρήστης (π.χ. PLAKETES: οι ετικέτες Πλακετών ζουν στην καρτέλα 4 του Excel)
    __table_args__ = (UniqueConstraint("source", "label_key", name="uq_material_label_map"),)

class CommercialExport(Base, TimestampMixin):
    """Εξαγωγή (πώληση/αποστολή) ΕΜΠΟΡΙΚΟΥ υλικού από τα Windows (καρτέλα Εμπορικά): αφαιρεί κιλά/τεμάχια από το απόθεμα της Αποθήκης. Ενεργή = μετρά."""
    __tablename__ = "commercial_exports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(String(36), ForeignKey("materials.id"), index=True)
    export_date: Mapped[date] = mapped_column(Date, index=True)
    kg: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    pieces: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

class MaterialInventoryEntry(Base, TimestampMixin):
    """Ζύγιση απογραφής (τριμηνιαία): μέσο αποθήκευσης (παλέτα/σάκος/χύμα) με καθαρά κιλά υλικού. ΔΕΝ προσμετράται στα «διαθέσιμα προς αποστολή»."""
    __tablename__ = "material_inventory_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_id: Mapped[str] = mapped_column(String(36), ForeignKey("materials.id"), index=True)
    storage_group_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    collection_medium_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("collection_media.id"), nullable=True, index=True)
    form: Mapped[str] = mapped_column(String(20))                       # PALLET | SACK_1KG | SACK_2KG | BULK
    gross_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    tare_weight: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    net_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="COUNTED")   # COUNTED | EXPORTED
    exported_lot_id: Mapped[str|None] = mapped_column(String(36), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

class ReadyMaterialMovement(Base):
    __tablename__ = "ready_material_movements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ready_material_lots.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(50), index=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    reason: Mapped[str|None] = mapped_column(Text, nullable=True)


# ---- Build 0.8: Loading orders and dispatch ----
class LoadingOrder(Base, TimestampMixin):
    __tablename__ = "loading_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    loading_number: Mapped[str] = mapped_column(String(70), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    carrier_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    vehicle_registration: Mapped[str|None] = mapped_column(String(40), nullable=True)
    max_allowed_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    selection_mode: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    dispatch_reason: Mapped[str|None] = mapped_column(String(200), nullable=True)
    weighbridge_number: Mapped[str|None] = mapped_column(String(80), nullable=True)
    dispatch_document_number: Mapped[str|None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    first_recipient: Mapped[str|None] = mapped_column(String(200), nullable=True)
    mgmt_operation: Mapped[str|None] = mapped_column(String(40), nullable=True)
    tracking_document: Mapped[str|None] = mapped_column(String(120), nullable=True)
    destination_country: Mapped[str|None] = mapped_column(String(80), nullable=True)
    container_number: Mapped[str|None] = mapped_column(String(120), nullable=True)
    gr_notification_no: Mapped[str|None] = mapped_column(String(120), nullable=True)
    bill_of_lading: Mapped[str|None] = mapped_column(String(120), nullable=True)
    # Προετοιμασία φόρτωσης (σχέδιο: δεν δεσμεύει αποθήκη μέχρι την οριστικοποίηση)
    driver_name: Mapped[str|None] = mapped_column(String(200), nullable=True)
    eka_code: Mapped[str|None] = mapped_column(String(60), nullable=True)
    reptool_code: Mapped[str|None] = mapped_column(String(80), nullable=True)
    delivery_date: Mapped[str|None] = mapped_column(String(10), nullable=True)
    prep_mode: Mapped[str|None] = mapped_column(String(10), nullable=True)
    customer_address: Mapped[str|None] = mapped_column(String(300), nullable=True)
    cancelled_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str|None] = mapped_column(String(36), nullable=True)

class LoadingPlanItem(Base):
    """Σχεδιασμένο μέσο συλλογής σε πρόχειρο της Προετοιμασίας. ΔΕΝ είναι δέσμευση: το lot μένει διαθέσιμο."""
    __tablename__ = "loading_plan_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    loading_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("loading_orders.id", ondelete="CASCADE"), index=True)
    ready_material_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ready_material_lots.id"), index=True)
    __table_args__ = (UniqueConstraint("loading_order_id","ready_material_lot_id",name="uq_loading_plan_item"),)

class LoadingBulkItem(Base):
    """Χύμα κιλά (από το υπολογιζόμενο απόθεμα Υλικών: παραγωγή − αποστολές) σε πρόχειρο/φορτίο της Προετοιμασίας.
    ΔΕΝ δεσμεύουν απόθεμα· αφαιρούνται ΜΟΝΟ στην οριστικοποίηση (MaterialShipmentEntry, source=LOADING, notes=LOADING:<id φόρτωσης>)."""
    __tablename__ = "loading_bulk_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    loading_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("loading_orders.id", ondelete="CASCADE"), index=True)
    category_group: Mapped[str] = mapped_column(String(30))
    material_label: Mapped[str] = mapped_column(String(150))
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    shortage_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)      # υπέρβαση αποθέματος (kg) που επιβεβαιώθηκε στην οριστικοποίηση
    shortage_reason: Mapped[str|None] = mapped_column(Text, nullable=True)       # υποχρεωτικός λόγος υπέρβασης
    __table_args__ = (UniqueConstraint("loading_order_id","material_label",name="uq_loading_bulk_item"),)

class LoadingReservation(Base):
    __tablename__ = "loading_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    loading_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("loading_orders.id", ondelete="CASCADE"), index=True)
    ready_material_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ready_material_lots.id"), index=True)
    reserved_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    status: Mapped[str] = mapped_column(String(40), default="RESERVED", index=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

class EquipmentItem(Base, TimestampMixin):
    """Durable equipment registry: hand tools and PPE (kind='TOOL'|'PPE'), each optionally
    checked out to one employee at a time -- an employee's own "toolkit" is just the set of
    items with assigned_employee_id == them, no separate table needed. PPE additionally tracks
    a certification/inspection expiry date; tools leave it null."""
    __tablename__ = "equipment_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(10), index=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str|None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE", index=True)
    assigned_employee_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("employees.id"), nullable=True, index=True)
    assigned_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    certification_expiry: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ConsumableType(Base, TimestampMixin):
    __tablename__ = "consumable_types"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    unit: Mapped[str] = mapped_column(String(20), default="τεμ")
    low_stock_threshold: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class ConsumableLot(Base, TimestampMixin):
    """A received batch of a consumable type, so each batch can carry its own expiry date --
    total current stock for a type is the sum of its active lots' quantity."""
    __tablename__ = "consumable_lots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    consumable_type_id: Mapped[str] = mapped_column(String(36), ForeignKey("consumable_types.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14,3))
    received_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expiry_date: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    notes: Mapped[str|None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class LoadingActual(Base):
    __tablename__ = "loading_actuals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    loading_order_id: Mapped[str] = mapped_column(String(36), ForeignKey("loading_orders.id", ondelete="CASCADE"), index=True)
    ready_material_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ready_material_lots.id"), index=True)
    loaded_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    loaded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


# ---- Build 0.9: Galaxy integration queue and mappings ----
class IntegrationMapping(Base, TimestampMixin):
    __tablename__ = "integration_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    system: Mapped[str] = mapped_column(String(40), index=True)
    mapping_type: Mapped[str] = mapped_column(String(60), index=True)
    internal_key: Mapped[str] = mapped_column(String(160), index=True)
    external_key: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("system","mapping_type","internal_key",name="uq_integration_mapping"),)

class SyncEvent(Base):
    __tablename__ = "sync_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    system: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    operation: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    payload_json: Mapped[str|None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    external_id: Mapped[str|None] = mapped_column(String(150), nullable=True)
    error_message: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


# ---- Build 1.0: configurable direct-processing path ----
class DirectProcessingMapping(Base, TimestampMixin):
    __tablename__ = "direct_processing_mappings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), unique=True, index=True)
    output_material_id: Mapped[str] = mapped_column(String(36), ForeignKey("materials.id"), index=True)
    output_form: Mapped[str] = mapped_column(String(40), default="BULK")
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class DirectProcessingEvent(Base, TimestampMixin):
    __tablename__ = "direct_processing_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_stock_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_stock_lots.id"), index=True)
    mapping_id: Mapped[str] = mapped_column(String(36), ForeignKey("direct_processing_mappings.id"), index=True)
    output_lot_id: Mapped[str] = mapped_column(String(36), ForeignKey("ready_material_lots.id"), index=True)
    processed_weight: Mapped[Decimal] = mapped_column(Numeric(14,3))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))

# ---- Build 2.5.36: Ανακύκλωση Συσκευών Α.Ε. (electrocycle) live order-flow mirror ----
class ElectrocycleOrder(Base, TimestampMixin):
    """A read-only cache of one row from the external portal's 'Ροή Εντολών' grid for
    today (Σημείο Παράδοσης 001), refreshed on a timer by integrations/electrocycle.py.
    This is a monitoring mirror, not our own receipt ledger -- it is never turned into
    InboundTrip/Receipt rows automatically, only shown alongside them."""
    __tablename__ = "electrocycle_orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_no: Mapped[str] = mapped_column(String(60), index=True)
    execution_route: Mapped[str|None] = mapped_column(String(60), nullable=True)
    delivery_route: Mapped[str|None] = mapped_column(String(60), nullable=True)
    sender: Mapped[str|None] = mapped_column(String(200), nullable=True)
    pickup_point: Mapped[str|None] = mapped_column(String(200), nullable=True)
    address: Mapped[str|None] = mapped_column(String(200), nullable=True)
    city: Mapped[str|None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str|None] = mapped_column(String(20), nullable=True)
    carrier: Mapped[str|None] = mapped_column(String(200), nullable=True)
    collection_medium: Mapped[str|None] = mapped_column(String(200), nullable=True)
    raw_json: Mapped[str|None] = mapped_column(Text, nullable=True)
    source_date: Mapped[str] = mapped_column(String(10), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

class MaterialGroupOverride(Base, TimestampMixin):
    """User-driven reclassification of a material's value group (Αξιοποιήσιμα /
    Ειδικής Διαχείρισης / Προς Απόρριψη) in the Υλικά screen, set by dragging a
    material to a different group button. This is a convenience grouping by the
    material's value, unrelated to its WEEE/registry classification -- moving a
    material only changes which group's monthly total it counts toward going
    forward (see main.py material group resolution). sort_order controls display
    position within its group (also drag-driven)."""
    __tablename__ = "material_group_overrides"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_label: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    category_group: Mapped[str] = mapped_column(String(30), index=True)
    sort_order: Mapped[int] = mapped_column(default=0)

class ElectrocycleSyncStatus(Base):
    """Single-row status of the last sync attempt, surfaced to the UI so a failed/expired
    login (e.g. the remembered-device trust lapsed and OTP is needed again) is visible
    instead of the panel silently going stale."""
    __tablename__ = "electrocycle_sync_status"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    last_attempt_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str|None] = mapped_column(Text, nullable=True)


# ---- Build 2.5.36: Απογραφή (τρέχον έτος) quarterly stock-reconciliation report ----
class MaterialHerGroup(Base, TimestampMixin):
    """Maps a granular production/shipment material_label (MaterialOutputEntry / MaterialShipmentEntry)
    to its roll-up "Περιγραφή HER" group, per the company's Ylika.xlsx reference file (row 4 = HER
    group, row 5 = the ERP label that equals material_label here). Powers the live per-quarter
    aggregation in the Απογραφή report -- e.g. ΑΛΟΥΜΙΝΙΟ ΣΚΛΗΡΟ/ΜΑΛΑΚΟ/ΠΡΟΦΙΛ/... all roll up to
    "Αλουμίνιο"."""
    __tablename__ = "material_her_groups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    material_label: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    her_group: Mapped[str] = mapped_column(String(150), index=True)

class InventoryReportRow(Base, TimestampMixin):
    """One row of the Απογραφή (τρέχον έτος) report, seeded once from ΑΠΟΓΡΑΦΗ 2026.xlsm's "Αποθήκη"
    sheet (row order preserved via sort_order). her_group is null for the sheet's many hidden
    placeholder rows (finer REPTOOL sub-codes with no real activity yet) -- those just show their
    frozen 2025/2026 figures from the import; rows with her_group set are computed live from
    material_output_entries / material_shipment_entries / inventory_count_entries via
    MaterialHerGroup."""
    __tablename__ = "inventory_report_rows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    sort_order: Mapped[int] = mapped_column(Integer, index=True)
    group_name: Mapped[str|None] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[str|None] = mapped_column(String(100), nullable=True)
    reptool_code: Mapped[str|None] = mapped_column(String(60), nullable=True)
    description_en: Mapped[str|None] = mapped_column(String(255), nullable=True)
    her_group: Mapped[str|None] = mapped_column(String(150), nullable=True, index=True)
    eka_code: Mapped[str|None] = mapped_column(String(40), nullable=True)
    baseline_stock_2025: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    frozen_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

class InventoryActualStock(Base, TimestampMixin):
    """ΠΡΑΓΜΑΤΙΚΟ ΑΠΟΘΕΜΑ -- the physically-counted stock the user types in by hand for one report
    row, for one quarter of one year. ΔΙΑΦΟΡΑ is computed on read (ΑΠΟΘΕΜΑ - ΠΡΑΓΜΑΤΙΚΟ ΑΠΟΘΕΜΑ), not
    stored."""
    __tablename__ = "inventory_actual_stock"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    row_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_report_rows.id", ondelete="CASCADE"), index=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    updated_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    __table_args__ = (UniqueConstraint("row_id", "year", "quarter", name="uq_inventory_actual_stock"),)

class InventoryCountEntry(Base, TimestampMixin):
    """Ποσότητα απογραφής -- physically-counted quantity of a not-yet-ready material, typed in by hand
    in the Υλικά tab only on quarter-closing months (Μάρτιος/Ιούνιος/Σεπτέμβριος/Δεκέμβριος). Not part
    of "Τρέχον απόθεμα"; feeds into the Απογραφή report's ΑΠΟΘΕΜΑ column (ready-to-ship stock + this)
    and, per the mass-balance logic still to come, into that quarter's outgoing-materials balance."""
    __tablename__ = "inventory_count_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    year: Mapped[int] = mapped_column(Integer, index=True)
    quarter: Mapped[int] = mapped_column(Integer)
    material_label: Mapped[str] = mapped_column(String(150), index=True)
    weight_kg: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    updated_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    __table_args__ = (UniqueConstraint("year", "quarter", "material_label", name="uq_inventory_count_entry"),)

class MaterialCorrectionEntry(Base, TimestampMixin):
    """Διορθώσεις -- a manual +/- adjustment to a material's monthly kg and/or piece count in Υλικά,
    entered by logistics/management (not the android operator). Multiple per material per month are
    expected (e.g. a stock-take finds 2 extra bags one week, a mis-weighed lot gets corrected the
    next) -- same "several small entries, tagged and summed" pattern as Παραγωγή's own correction row
    (see notes=='Διόρθωση αρχείου παραγωγής' entries in MaterialOutputEntry), but as its own small
    table instead of overloading MaterialOutputEntry (which represents real production output, not
    manual adjustments) with signed deltas."""
    __tablename__ = "material_correction_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    work_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    material_label: Mapped[str] = mapped_column(String(150), index=True)
    weight_kg_delta: Mapped[Decimal] = mapped_column(Numeric(14,3), default=0)
    piece_delta: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str|None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

class DeviceMaterialYield(Base, TimestampMixin):
    """Ανάλυση συσκευών -- reference/recipe percentages (not derived from live transactions):
    "1 kg of this WEEE category is expected to yield X% of this material", from manual measurements
    that get updated over time. This is the base for a future ΑΗΗΕ production-analysis report, not a
    record of what actually happened -- keep it strictly separate from real production/output ledgers.
    Rows key off InventoryReportRow (the Απογραφή sheet's own row list/order), not Material, per
    explicit instruction to mirror Απογραφή exactly -- same 153 rows, same order, hidden/unused ones
    included -- rather than the separate 252-row Material registry, which uses a different naming
    space (her_group barely overlaps Material.internal_name, confirmed empirically)."""
    __tablename__ = "device_material_yields"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), index=True)
    report_row_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_report_rows.id"), index=True)
    percentage: Mapped[Decimal] = mapped_column(Numeric(9,4), default=0)
    updated_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    source_batch_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("device_yield_batches.id"), nullable=True)
    __table_args__ = (UniqueConstraint("weee_category_id", "report_row_id", name="uq_device_material_yield"),)

class DeviceYieldBatch(Base, TimestampMixin):
    """One real measured batch (a physical dismantling/weighing session) for one WEEE category --
    the historical source behind DeviceMaterialYield's percentages. Several batches can exist for
    the same category over time; sample_size (pieces measured) weights the "average of all batches"
    option in the UI. label is a short human name (e.g. the source filename's own title) shown in the
    picker when a category has more than one batch."""
    __tablename__ = "device_yield_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    weee_category_id: Mapped[str] = mapped_column(String(36), ForeignKey("weee_categories.id"), index=True)
    label: Mapped[str] = mapped_column(String(200))
    sample_size: Mapped[int|None] = mapped_column(Integer, nullable=True)
    total_input_kg: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    total_output_kg: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    source_file: Mapped[str|None] = mapped_column(String(300), nullable=True)
    created_by_user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)

class DeviceYieldBatchCell(Base, TimestampMixin):
    """One material's measured percentage within a DeviceYieldBatch."""
    __tablename__ = "device_yield_batch_cells"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("device_yield_batches.id", ondelete="CASCADE"), index=True)
    report_row_id: Mapped[str] = mapped_column(String(36), ForeignKey("inventory_report_rows.id"), index=True)
    weight_kg: Mapped[Decimal|None] = mapped_column(Numeric(14,3), nullable=True)
    percentage: Mapped[Decimal] = mapped_column(Numeric(9,4), default=0)
    __table_args__ = (UniqueConstraint("batch_id", "report_row_id", name="uq_device_yield_batch_cell"),)


class MaterialTab(Base, TimestampMixin):
    """Καρτέλες της σελίδας Υλικά που ορίζονται από τον χρήστη + οι 4 σύστημα (Αξιοποιήσιμα, Ειδικής Διαχείρισης, Πλακέτες, Προς Απόρριψη).
    code = ο ΣΤΑΘΕΡΟΣ εσωτερικός κωδικός (δεν αλλάζει ποτέ με μετονομασία)· είναι η τιμή που γράφεται ως category_group (αντικατάσταση ομάδας) και ως sheet (αντιστοίχιση ετικέτας).
    Η διαγραφή είναι απενεργοποίηση (active=False): δεν σβήνεται γραμμή. is_system: οι 4 σημερινές δεν διαγράφονται/μετονομάζονται."""
    __tablename__ = "material_tabs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(default=0)
    is_system: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)


class ActionHistory(Base):
    """Καθολικό ιστορικό ενεργειών Windows για Αναίρεση/Επανάληψη (Φάση 1: μόνο ασφαλείς ενέργειες + «κλεισίματα» ως φραγμοί).
    kind: ενέργεια που αναιρείται (mat_corr_add / mat_corr_del / receipt_delete) ή 'closing' (κλείσιμο φόρτωσης/παραλαβής/ΔΠΠ: ΠΟΤΕ δεν αναιρείται από εδώ).
    subjects: στοιχεία που αγγίζει η ενέργεια (π.χ. 'mat:ΥΛΙΚΟ', 'receipt:ID')· δύο ενέργειες συγκρούονται μόνο αν μοιράζονται στοιχείο.
    status: DONE (ενεργή) / UNDONE (αναιρέθηκε, διαθέσιμη για Επανάληψη)."""
    __tablename__ = "action_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str|None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    username: Mapped[str|None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    label: Mapped[str] = mapped_column(String(300))
    subjects: Mapped[str] = mapped_column(Text, default="[]")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(10), default="DONE", index=True)
    undoable: Mapped[bool] = mapped_column(Boolean, default=True)
