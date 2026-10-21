from pydantic import BaseModel, ConfigDict
from decimal import Decimal
from datetime import datetime

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class LoginRequest(BaseModel):
    username: str
    password: str

class OrgUnitCreate(BaseModel):
    code: str
    name_el: str
    name_en: str|None = None
    parent_id: str|None = None
    sort_order: int = 0
    position: str|None = None  # legacy single-position field; kept for compatibility
    positions: list[str] = []
    profile: str|None = None  # PRODUCTION | SUPPORT | MANAGEMENT

class OrgUnitOut(OrgUnitCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    active: bool


class EmployeeCreate(BaseModel):
    full_name: str
    phone: str|None = None
    default_org_unit_id: str|None = None  # compatibility with older clients
    org_unit_ids: list[str] = []

class EmployeeOut(EmployeeCreate):
    id: str
    employee_code: str
    org_unit_names: list[str] = []
    active: bool

class ProductionWorkEntryCreate(BaseModel):
    work_date: datetime
    org_unit_id: str
    employee_id: str|None = None
    weee_category_id: str
    weight_kg: Decimal
    supplier_group: str = "OTHER"
    source: str = "WINDOWS"
    notes: str|None = None
    transfer_id: str|None = None

class TransferWeightIn(BaseModel):
    weight: Decimal
    reason: str|None = None

class ProductionWorkEntryOut(ProductionWorkEntryCreate):
    id: str
    active: bool

class ProductionWorkEntryUpdate(BaseModel):
    work_date: datetime|None = None
    org_unit_id: str|None = None
    employee_id: str|None = None
    weee_category_id: str|None = None
    weight_kg: Decimal|None = None
    supplier_group: str|None = None
    notes: str|None = None
    reason: str|None = None

class ProductionAttendanceUpsert(BaseModel):
    work_date: datetime
    employee_id: str
    status: str|None = None  # PRESENT|ABSENT|LEFT
    org_unit_id: str|None = None
    position_text: str|None = None
    since_at: datetime|None = None
    late: bool|None = None  # True = ΑΡΓΟΠΟΡΙΑ, False = εγκαίρως, None = όπως είναι/αυτόματα
    arrived_at: datetime|None = None  # χειροκίνητη ώρα άφιξης (Παρουσιολόγιο Windows)

class AttendanceUnitsIn(BaseModel):
    work_date: datetime
    employee_id: str
    action: str  # add | remove
    unit_id: str

class ProductionAttendanceOut(ProductionAttendanceUpsert):
    id: str
    event_id: str|None = None
    arrived_at: datetime|None = None

class ShiftStartIn(BaseModel):
    shift_start: str|None = None
    shift_end: str|None = None

class ProductionDayMaterialIn(BaseModel):
    work_date: datetime
    org_unit_id: str
    employee_id: str|None = None
    weee_category_id: str
    weight_kg: Decimal
    source: str = "WINDOWS"

class OrganizationCreate(BaseModel):
    legal_name: str
    trade_name: str|None = None
    tax_id: str|None = None
    email: str|None = None
    phone: str|None = None
    supplier_kind: str|None = None
    supplier_source: str|None = None
    permit_number: str|None = None
    permit_ada: str|None = None
    roles: list[str] = []


class OrganizationUpdate(BaseModel):
    legal_name: str
    trade_name: str|None = None
    tax_id: str|None = None
    email: str|None = None
    phone: str|None = None
    supplier_kind: str|None = None
    supplier_source: str|None = None
    permit_number: str|None = None
    permit_ada: str|None = None
    roles: list[str] = []

class OrganizationMergeRequest(BaseModel):
    target_id: str
    source_ids: list[str]

class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    legal_name: str
    trade_name: str|None
    tax_id: str|None
    email: str|None
    phone: str|None
    galaxy_id: str|None
    active: bool
    supplier_kind: str|None = None
    supplier_source: str|None = None
    permit_number: str|None = None
    permit_ada: str|None = None



class SupplierBranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    supplier_id: str
    name: str
    active: bool

class OrganizationSearchOut(BaseModel):
    id: str
    legal_name: str
    trade_name: str|None = None
    tax_id: str|None = None
    phone: str|None = None
    extra: str|None = None

class CarrierDriverCreate(BaseModel):
    full_name: str
    phone: str|None = None
    active: bool = True

class CarrierDriverOut(CarrierDriverCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    carrier_id: str

class CarrierVehicleCreate(BaseModel):
    plate_number: str
    active: bool = True

class CarrierVehicleOut(CarrierVehicleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    carrier_id: str

class VisitorLogCreate(BaseModel):
    visit_date: datetime
    full_name: str
    arrival_at: datetime|None = None
    departure_at: datetime|None = None
    reason: str

class VisitorLogOut(VisitorLogCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_type: str
    source_id: str|None = None

class WEEECategoryCreate(BaseModel):
    code: str
    description_el: str
    parent_code: str|None = None
    is_internal_subcategory: bool = False
    average_weight: Decimal|None = None
    her_description: str|None = None
    eka_code: str|None = None
    processable: bool = True

class WEEECategoryOut(WEEECategoryCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    active: bool

class MaterialCreate(BaseModel):
    internal_code: str
    internal_name: str
    galaxy_code: str|None = None
    galaxy_description: str|None = None
    genre: str|None = None
    official_description: str|None = None
    her_description: str|None = None
    eka_code: str|None = None
    reptool_code: str|None = None
    reptool_description: str|None = None
    is_precious: bool = False
    export_step_kg: Decimal = Decimal("0.500")
    storage_group_id: str|None = None   # Ομάδα αποθήκης (προαιρετικό)

class StorageGroupIn(BaseModel):
    name: str
    active: bool = True

class StorageGroupAssignIn(BaseModel):
    material_ids: list[str]
    storage_group_id: str|None = None

class MaterialOut(MaterialCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    active: bool

class MediumTypeCreate(BaseModel):
    code: str
    name_el: str
    default_tare_weight: Decimal|None = None
    requires_unique_number: bool = False
    never_reuse_number: bool = False

class MediumTypeOut(MediumTypeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    active: bool
    usage: str = "BOTH"
    tare_fixed: bool = False
    short_code: str|None = None
    single_use: bool = False

class MediumTypeNew(BaseModel):
    name_el: str
    usage: str = "OUT"
    tare_fixed: bool = False
    default_tare_weight: Decimal|None = None
    short_code: str|None = None
    single_use: bool = False

class MediumTypeRename(BaseModel):
    name_el: str

class MediumTypeEdit(BaseModel):
    name_el: str
    short_code: str|None = None
    usage: str
    tare_fixed: bool = False
    default_tare_weight: Decimal|None = None
    single_use: bool = False

class MediumTypeTare(BaseModel):
    default_tare_weight: Decimal

class MediumMove(BaseModel):
    ids: list[str]
    target_type_id: str

class MediumTypeUsageIn(BaseModel):
    usage: str

class MediumCreate(BaseModel):
    type_id: str
    code: str|None = None
    tare_weight: Decimal|None = None
    linked_loading_order_id: str|None = None

class MediumOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    type_id: str
    code: str
    tare_weight: Decimal|None
    status: str
    active: bool
    linked_loading_order_id: str|None = None
    in_use: bool = False        # «Σε χρήση»: κρατά απόθεμα / έχει κατάσταση άλλη από AVAILABLE (υπολογίζεται στη λίστα)

class WEEEDisplayUpdate(BaseModel):
    display_name: str
    display_group: str|None = None

class WEEEInternalSubcategoryCreate(BaseModel):
    parent_category_id: str
    display_name: str

from datetime import datetime

class ContainerCreate(BaseModel):
    container_number: str
    owner_organization_id: str|None = None
    tare_weight: Decimal
    notes: str|None = None

class ContainerOut(ContainerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    active: bool

class ReceiptLoadCreate(BaseModel):
    supplier_id: str
    order_number: str|None = None
    incoming_container_number: str|None = None
    incoming_container_tare: Decimal|None = None
    outgoing_container_id: str|None = None
    outgoing_container_tare: Decimal|None = None
    gross_weight: Decimal|None = None
    tare_weight: Decimal|None = None
    notes: str|None = None
    dpp_number: int|None = None
    weighbridge_number: str|None = None
    dispatch_note_number: str|None = None
    seal_number: str|None = None

class ReceiptCreate(BaseModel):
    receipt_type: str
    receipt_date: datetime
    carrier_id: str|None = None
    driver_name: str|None = None
    vehicle_registration: str|None = None
    notes: str|None = None
    aggregate_weighbridge_number: str|None = None
    loads: list[ReceiptLoadCreate]

class ReceiptLoadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    load_sequence: int
    supplier_id: str
    order_number: str|None
    incoming_container_number: str|None
    incoming_container_tare: Decimal|None
    outgoing_container_id: str|None
    outgoing_container_tare: Decimal|None
    gross_weight: Decimal|None
    tare_weight: Decimal|None
    net_weight: Decimal|None
    status: str
    ready_for_sorting_at: datetime|None
    notes: str|None
    dpp_number: int|None
    weighbridge_number: str|None
    dispatch_note_number: str|None
    seal_number: str|None

class ReceiptOut(BaseModel):
    id: str
    receipt_number: str
    receipt_type: str
    receipt_date: datetime
    carrier_id: str|None
    driver_name: str|None
    vehicle_registration: str|None
    status: str
    notes: str|None
    aggregate_weighbridge_number: str|None
    deleted_at: datetime|None = None
    loads: list[ReceiptLoadOut]

class ReceiptStatusOut(BaseModel):
    id: str
    receipt_number: str
    status: str
    loads_ready: int
    loads_total: int

class SortingStartOut(BaseModel):
    id: str
    inbound_load_id: str
    status: str

class SortingEntryCreate(BaseModel):
    weee_category_id: str
    collection_medium_id: str|None = None
    entry_type: str = "MEDIUM"
    raw_weight: Decimal|None = None
    piece_count: int|None = None
    notes: str|None = None

class SortingEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    session_id: str
    weee_category_id: str
    collection_medium_id: str|None
    entry_type: str
    raw_weight: Decimal|None
    approved_weight: Decimal|None
    piece_count: int|None
    notes: str|None
    warning: str|None = None      # π.χ. «το μέσο περιέχει ήδη άλλη κατηγορία· ο κωδικός μένει»

class SortingSessionOut(BaseModel):
    id: str
    inbound_load_id: str
    status: str
    net_weight: Decimal|None
    sorting_weight: Decimal
    difference: Decimal|None
    requires_management_approval: bool
    entries: list[SortingEntryOut]

class SortingMetaUpdate(BaseModel):
    foreign_materials: str|None = None
    foreign_weight: Decimal|None = None
    special_waste: str|None = None
    special_waste_weight: Decimal|None = None
    load_pure: bool = False
    check_special: bool = False
    check_kday: bool = False
    check_non_integer: bool = False

class SortingAdjustmentCreate(BaseModel):
    new_weight: Decimal
    reason: str

class LogisticsReviewCreate(BaseModel):
    requires_management_approval: bool = False
    notes: str|None = None

class DayStatusOut(BaseModel):
    date: str
    color: str
    total_loads: int
    red: int
    yellow: int
    green: int
    overdue: int


# ---- Build 0.6 ----
class WEEEStockLotOut(BaseModel):
    id: str
    inbound_load_id: str
    weee_category_id: str
    weee_code: str
    weee_description: str
    collection_medium_id: str|None
    medium_code: str|None
    location_code: str
    original_weight: Decimal
    available_weight: Decimal
    piece_count: int|None
    status: str

class ProductionTransferItemCreate(BaseModel):
    stock_lot_id: str
    weight: Decimal|None = None

class ProductionTransferCreate(BaseModel):
    destination_org_unit_id: str
    items: list[ProductionTransferItemCreate]
    notes: str|None = None

class ProductionTransferItemOut(BaseModel):
    stock_lot_id: str
    weight: Decimal
    weee_code: str
    medium_code: str|None

class ProductionTransferOut(BaseModel):
    id: str
    transfer_number: str
    destination_org_unit_id: str
    status: str
    items: list[ProductionTransferItemOut]


# ---- Build 0.7 ----
class ProductionBalanceOut(BaseModel):
    id: str
    transfer_item_id: str
    org_unit_id: str
    weee_code: str
    medium_code: str|None
    initial_weight: Decimal
    current_remaining_weight: Decimal
    processed_weight: Decimal
    status: str

class ProductionRemainderCreate(BaseModel):
    balance_id: str
    remaining_weight: Decimal
    notes: str|None = None

class ProductionRemainderOut(BaseModel):
    balance_id: str
    previous_remaining_weight: Decimal
    remaining_weight: Decimal
    processed_since_previous: Decimal
    status: str

class ReadyMaterialCreate(BaseModel):
    material_id: str
    output_form: str
    source_org_unit_id: str|None = None
    collection_medium_id: str|None = None
    gross_weight: Decimal|None = None
    tare_weight: Decimal|None = None
    net_weight: Decimal|None = None
    notes: str|None = None

class ReadyMaterialOut(BaseModel):
    id: str
    lot_number: str
    material_id: str
    material_code: str
    material_name: str
    output_form: str
    medium_code: str|None
    net_weight: Decimal
    status: str
    source_org_unit_id: str|None
    created_at: str


# ---- Build 0.8 ----
class LoadingOrderCreate(BaseModel):
    customer_id: str
    carrier_id: str|None = None
    vehicle_registration: str|None = None
    max_allowed_weight: Decimal
    selection_mode: str
    dispatch_reason: str|None = None
    weighbridge_number: str|None = None
    dispatch_document_number: str|None = None
    notes: str|None = None
    first_recipient: str|None = None
    mgmt_operation: str|None = None
    tracking_document: str|None = None
    destination_country: str|None = None
    container_number: str|None = None
    gr_notification_no: str|None = None
    bill_of_lading: str|None = None

class LoadingDaDetailsIn(BaseModel):
    first_recipient: str|None = None
    mgmt_operation: str|None = None
    tracking_document: str|None = None
    destination_country: str|None = None
    container_number: str|None = None
    gr_notification_no: str|None = None
    bill_of_lading: str|None = None

class LoadingLotAction(BaseModel):
    ready_material_lot_id: str
    weight: Decimal|None = None

class LoadingOrderOut(BaseModel):
    id: str
    loading_number: str
    customer_id: str
    carrier_id: str|None
    vehicle_registration: str|None
    max_allowed_weight: Decimal
    selection_mode: str
    status: str
    reserved_weight: Decimal
    loaded_weight: Decimal
    remaining_capacity: Decimal
    dispatch_reason: str|None
    dispatch_document_number: str|None = None
    weighbridge_number: str|None = None
    driver_name: str|None = None
    eka_code: str|None = None
    reptool_code: str|None = None
    delivery_date: str|None = None
    prep_mode: str|None = None
    first_recipient: str|None = None
    mgmt_operation: str|None = None
    tracking_document: str|None = None
    destination_country: str|None = None
    container_number: str|None = None
    gr_notification_no: str|None = None
    bill_of_lading: str|None = None


# ---- Build 0.9 ----
class IntegrationMappingCreate(BaseModel):
    mapping_type: str
    internal_key: str
    external_key: str

class IntegrationMappingOut(IntegrationMappingCreate):
    id: str
    system: str
    active: bool

class SyncEnqueueCreate(BaseModel):
    entity_type: str
    entity_id: str
    operation: str = "UPSERT"
    payload: dict|None = None

class SyncEventOut(BaseModel):
    id: str
    system: str
    entity_type: str
    entity_id: str
    operation: str
    idempotency_key: str
    status: str
    attempts: int
    external_id: str|None
    error_message: str|None

class GalaxyStatusOut(BaseModel):
    connector_configured: bool
    pending: int
    failed: int
    synced: int
    mappings: int
    note: str


# ---- Build 1.0 ----
class DirectProcessingMappingCreate(BaseModel):
    weee_category_id: str
    output_material_id: str
    output_form: str = "BULK"
    requires_confirmation: bool = True

class DirectProcessingMappingOut(DirectProcessingMappingCreate):
    id: str
    active: bool

class DirectProcessCreate(BaseModel):
    confirm: bool = True
    source_org_unit_id: str|None = None
    notes: str|None = None

class OperationalDashboardOut(BaseModel):
    open_receipt_loads: int
    sorting_in_progress: int
    waiting_logistics: int
    waiting_management: int
    weee_stock_kg: Decimal
    production_open_kg: Decimal
    ready_stock_kg: Decimal
    open_loadings: int
    galaxy_pending: int
    today_received: int = 0   # εντολές της σημερινής ημέρας που έχουν παραληφθεί
    today_remaining: int = 0  # εντολές της ζωντανής ροής που απομένουν


# ---- Equipment / PPE / Consumables ----
class MaterialGroupOverrideSet(BaseModel):
    category_group: str
    sort_order: int = 0

class EquipmentItemCreate(BaseModel):
    kind: str
    code: str
    name: str
    category: str|None = None
    certification_expiry: datetime|None = None
    notes: str|None = None

class EquipmentItemUpdate(BaseModel):
    code: str|None = None
    name: str|None = None
    category: str|None = None
    certification_expiry: datetime|None = None
    notes: str|None = None

class EquipmentAssignCreate(BaseModel):
    employee_id: str

class ConsumableTypeCreate(BaseModel):
    code: str
    name: str
    unit: str = "τεμ"
    low_stock_threshold: Decimal|None = None
    notes: str|None = None

class ConsumableTypeUpdate(BaseModel):
    code: str|None = None
    name: str|None = None
    unit: str|None = None
    low_stock_threshold: Decimal|None = None
    notes: str|None = None

class ConsumableLotCreate(BaseModel):
    quantity: Decimal
    received_date: datetime
    expiry_date: datetime|None = None
    notes: str|None = None

class InventoryCountEntryIn(BaseModel):
    year: int
    quarter: int
    material_label: str
    weight_kg: Decimal

class InventoryRowHerGroupIn(BaseModel):
    her_group: str | None = None

class MaterialCorrectionIn(BaseModel):
    work_date: str
    material_label: str
    weight_kg_delta: Decimal = Decimal("0")
    piece_delta: int = 0
    reason: str | None = None

class MaterialCorrectionOut(BaseModel):
    id: str
    work_date: str
    material_label: str
    weight_kg_delta: Decimal
    piece_delta: int
    reason: str | None
    created_by: str | None
    created_at: str | None = None

class DeviceYieldCellIn(BaseModel):
    weee_category_id: str
    report_row_id: str
    percentage: Decimal

class DeviceYieldApplyBatchIn(BaseModel):
    weee_category_id: str
    batch_id: str | None = None

class LoadingBulkIn(BaseModel):
    material_label: str
    weight_kg: Decimal

class LoadingPrepIn(BaseModel):
    customer_id: str
    carrier_id: str|None = None
    vehicle_registration: str|None = None
    driver_name: str|None = None
    dispatch_reason: str|None = None
    eka_code: str|None = None
    reptool_code: str|None = None
    dispatch_document_number: str|None = None
    delivery_date: str|None = None
    notes: str|None = None
    max_allowed_weight: Decimal = Decimal('25000')
    lot_ids: list[str] = []
    bulk_items: list[LoadingBulkIn] = []
    allow_shortage: bool = False
    shortage_reason: str|None = None

class MediumBulkIds(BaseModel):
    ids: list[str]

class MediumBulkTare(BaseModel):
    ids: list[str]
    tare_weight: Decimal
