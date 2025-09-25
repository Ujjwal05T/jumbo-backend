from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum
from uuid import UUID

# ============================================================================
# STATUS ENUMS - Validation for status fields
# ============================================================================

class OrderStatus(str, Enum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PaymentType(str, Enum):
    BILL = "bill"
    CASH = "cash"

class OrderItemStatus(str, Enum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    IN_WAREHOUSE = "in_warehouse"
    COMPLETED = "completed"

class InventoryStatus(str, Enum):
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    CUTTING = "cutting"
    USED = "used"
    DAMAGED = "damaged"

class ProductionOrderStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PlanStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class PendingOrderStatus(str, Enum):
    PENDING = "pending"
    INCLUDED_IN_PLAN = "included_in_plan"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"

class InventoryItemStatus(str, Enum):
    AVAILABLE = "available"
    IN_DISPATCH = "in_dispatch"
    DISPATCHED = "dispatched"
    DAMAGED = "damaged"

class RollType(str, Enum):
    JUMBO = "jumbo"
    ROLL_118 = "118"
    CUT = "cut"

class ClientStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class UserStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"

class UserRole(str, Enum):
    SALES = "sales"
    PLANNER = "planner"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    SYSTEM = "system"

class PaperType(str, Enum):
    STANDARD = "standard"
    PREMIUM = "premium"
    RECYCLED = "recycled"
    SPECIALTY = "specialty"

class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

# ============================================================================
# MASTER SCHEMAS - Core reference data
# ============================================================================

# Client Master Schemas
class ClientMasterBase(BaseModel):
    company_name: str = Field(..., max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    gst_number: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)

class ClientMasterCreate(ClientMasterBase):
    created_by_id: UUID

class ClientMasterUpdate(BaseModel):
    company_name: Optional[str] = Field(None, max_length=255)
    email: Optional[str] = Field(None, max_length=255)
    gst_number: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = None
    contact_person: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    status: Optional[ClientStatus] = None

class ClientMaster(ClientMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable client ID (e.g., CL-001)")
    created_by_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# User Master Schemas
class UserMasterBase(BaseModel):
    name: str = Field(..., max_length=255)
    username: str = Field(..., max_length=50)
    role: UserRole = Field(..., description="User role: sales, planner, supervisor, admin")
    contact: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    status: UserStatus = Field(default=UserStatus.ACTIVE)

class UserMasterCreate(UserMasterBase):
    password: str = Field(..., min_length=6)  # Plain password for hashing

class UserMasterLogin(BaseModel):
    username: str = Field(..., max_length=50)
    password: str = Field(..., min_length=6)

class UserMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    password: Optional[str] = Field(None, min_length=6)  # Optional password for updates
    role: Optional[UserRole] = None
    contact: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=100)
    status: Optional[UserStatus] = None

class UserMaster(UserMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable user ID (e.g., USR-001)")
    created_at: datetime
    last_login: Optional[datetime] = None

    class Config:
        from_attributes = True

# Paper Master Schemas
class PaperMasterBase(BaseModel):
    name: str = Field(..., max_length=255)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    thickness: Optional[float] = Field(None, gt=0)
    type: PaperType = Field(default=PaperType.STANDARD)
    status: ClientStatus = Field(default=ClientStatus.ACTIVE)  # Reusing ClientStatus for consistency

class PaperMasterCreate(PaperMasterBase):
    created_by_id: UUID

class PaperMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    gsm: Optional[int] = Field(None, gt=0)
    bf: Optional[float] = Field(None, gt=0)
    shade: Optional[str] = Field(None, max_length=50)
    thickness: Optional[float] = Field(None, gt=0)
    type: Optional[PaperType] = None
    status: Optional[ClientStatus] = None

class PaperMaster(PaperMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable paper ID (e.g., PAP-001)")
    created_by_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Material Master Schemas
class MaterialMasterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    unit_of_measure: str = Field(..., min_length=1, max_length=20)
    current_quantity: float = Field(default=0, ge=0)

class MaterialMasterCreate(MaterialMasterBase):
    pass

class MaterialMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    unit_of_measure: Optional[str] = Field(None, min_length=1, max_length=20)
    current_quantity: Optional[float] = Field(None, ge=0)

class MaterialMaster(MaterialMasterBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Inward Challan Schemas
class InwardChallanBase(BaseModel):
    party_id: UUID
    vehicle_number: Optional[str] = Field(None, max_length=50)
    material_id: UUID
    slip_no: Optional[str] = Field(None, max_length=50)
    rst_no: Optional[str] = Field(None, max_length=50)
    gross_weight: Optional[float] = Field(None, ge=0)
    report: Optional[float] = Field(None, ge=0, description="Weight to be subtracted from net weight")
    net_weight: Optional[float] = Field(None, ge=0)
    final_weight: Optional[float] = Field(None, ge=0, description="Calculated as net_weight - report")
    rate: Optional[float] = Field(None, ge=0, description="Rate per unit")
    bill_no: Optional[str] = Field(None, max_length=50)
    cash: Optional[float] = Field(None, ge=0)
    time_in: Optional[str] = None
    time_out: Optional[str] = None

class InwardChallanCreate(InwardChallanBase):
    pass

class InwardChallanUpdate(BaseModel):
    party_id: Optional[UUID] = None
    vehicle_number: Optional[str] = Field(None, max_length=50)
    material_id: Optional[UUID] = None
    slip_no: Optional[str] = Field(None, max_length=50)
    rst_no: Optional[str] = Field(None, max_length=50)
    gross_weight: Optional[float] = Field(None, ge=0)
    report: Optional[float] = Field(None, ge=0, description="Weight to be subtracted from net weight")
    net_weight: Optional[float] = Field(None, ge=0)
    final_weight: Optional[float] = Field(None, ge=0, description="Calculated as net_weight - report")
    rate: Optional[float] = Field(None, ge=0, description="Rate per unit")
    bill_no: Optional[str] = Field(None, max_length=50)
    cash: Optional[float] = Field(None, ge=0)
    time_in: Optional[str] = None
    time_out: Optional[str] = None

class InwardChallan(InwardChallanBase):
    id: UUID
    serial_no: Optional[str] = Field(None, description="Auto-generated serial number in format 00001")
    date: datetime
    created_at: datetime

    class Config:
        from_attributes = True

# Outward Challan Schemas
class OutwardChallanBase(BaseModel):
    vehicle_number: Optional[str] = Field(None, max_length=50)
    driver_name: Optional[str] = Field(None, max_length=255)
    rst_no: Optional[str] = Field(None, max_length=50)
    purpose: Optional[str] = Field(None, max_length=255)
    time_in: Optional[str] = None
    time_out: Optional[str] = None
    party_name: Optional[str] = Field(None, max_length=255)
    gross_weight: Optional[float] = Field(None, ge=0)
    net_weight: Optional[float] = Field(None, ge=0)
    bill_no: Optional[str] = Field(None, max_length=50)

class OutwardChallanCreate(OutwardChallanBase):
    pass

class OutwardChallanUpdate(BaseModel):
    vehicle_number: Optional[str] = Field(None, max_length=50)
    driver_name: Optional[str] = Field(None, max_length=255)
    rst_no: Optional[str] = Field(None, max_length=50)
    purpose: Optional[str] = Field(None, max_length=255)
    time_in: Optional[str] = None
    time_out: Optional[str] = None
    party_name: Optional[str] = Field(None, max_length=255)
    gross_weight: Optional[float] = Field(None, ge=0)
    net_weight: Optional[float] = Field(None, ge=0)
    bill_no: Optional[str] = Field(None, max_length=50)

class OutwardChallan(OutwardChallanBase):
    id: UUID
    serial_no: Optional[str] = Field(None, description="Auto-generated serial number in format 00001")
    date: datetime
    created_at: datetime

    class Config:
        from_attributes = True

# ============================================================================
# TRANSACTION SCHEMAS - Business operations
# ============================================================================

# Order Item Schemas
class OrderItemBase(BaseModel):
    paper_id: UUID
    width_inches: float = Field(..., gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: float = Field(..., gt=0)
    amount: Optional[float] = Field(None, gt=0)
    
    # Note: Auto-calculation is handled in CRUD layer to avoid Pydantic V2 issues

class OrderItemCreate(OrderItemBase):
    pass

class OrderItemUpdate(BaseModel):
    paper_id: Optional[UUID] = None
    width_inches: Optional[float] = Field(None, gt=0)
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_kg: Optional[float] = Field(None, gt=0)
    rate: Optional[float] = Field(None, gt=0)
    amount: Optional[float] = Field(None, gt=0)
    quantity_fulfilled: Optional[int] = Field(None, ge=0)
    quantity_in_pending: Optional[int] = Field(None, ge=0)

class OrderItem(OrderItemBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable order item ID (e.g., ORI-001)")
    order_id: UUID
    quantity_fulfilled: int
    quantity_in_pending: int
    created_at: datetime
    updated_at: datetime
    
    # Include related data
    paper: Optional['PaperMaster'] = None

    class Config:
        from_attributes = True

# Order Master Schemas - Updated for multiple order items
class OrderMasterBase(BaseModel):
    client_id: UUID
    priority: Priority = Field(default=Priority.NORMAL)
    payment_type: PaymentType = Field(default=PaymentType.BILL)
    delivery_date: Optional[datetime] = None

class OrderMasterCreate(OrderMasterBase):
    created_by_id: UUID
    order_items: List[OrderItemCreate] = Field(..., min_items=1, description="List of order items with different papers, widths and quantities")

class OrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    payment_type: Optional[PaymentType] = None
    delivery_date: Optional[datetime] = None
    status: Optional[OrderStatus] = None

class OrderMasterUpdateWithItems(BaseModel):
    priority: Optional[Priority] = None
    payment_type: Optional[PaymentType] = None
    delivery_date: Optional[datetime] = None
    order_items: List[OrderItemCreate] = Field(..., min_items=1, description="Updated list of order items")

class OrderMaster(OrderMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable order ID (e.g., ORD-2025-001)")
    status: OrderStatus
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    
    # Include related data
    client: Optional['ClientMaster'] = None
    order_items: List[OrderItem] = Field(default_factory=list)

    class Config:
        from_attributes = True

# Pending Order Master Schemas
class PendingOrderMasterBase(BaseModel):
    order_id: UUID
    order_item_id: UUID
    paper_id: UUID
    width_inches: float = Field(..., gt=0)
    quantity_pending: int = Field(..., gt=0)
    reason: str = Field(..., max_length=100)

class PendingOrderMasterCreate(PendingOrderMasterBase):
    pass

class PendingOrderMasterUpdate(BaseModel):
    status: Optional[PendingOrderStatus] = None
    production_order_id: Optional[UUID] = None

class PendingOrderMaster(PendingOrderMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable pending order ID (e.g., POM-001)")
    status: PendingOrderStatus
    production_order_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    
    # Include related data
    original_order: Optional[OrderMaster] = None
    order_item: Optional[OrderItem] = None
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# Pending Order Item Schemas - New model for service compatibility
class PendingOrderItemBase(BaseModel):
    original_order_id: UUID
    width_inches: float = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    quantity_pending: int = Field(..., gt=0)
    reason: str = Field(default="no_suitable_jumbo", max_length=100)

class PendingOrderItemCreate(PendingOrderItemBase):
    created_by_id: Optional[UUID] = None

class PendingOrderItemUpdate(BaseModel):
    status: Optional[PendingOrderStatus] = None
    production_order_id: Optional[UUID] = None
    resolved_at: Optional[datetime] = None

class PendingOrderItem(PendingOrderItemBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable pending order item ID (e.g., POI-001)")
    status: PendingOrderStatus
    production_order_id: Optional[UUID] = None
    created_by_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    quantity_fulfilled: Optional[int] = Field(default=0, description="Number of items fulfilled")
    
    # Plan generation tracking fields (kept for database compatibility)
    generated_cut_rolls_count: Optional[int] = Field(default=0, description="Number of cut rolls generated from this pending order")
    plan_generation_date: Optional[datetime] = Field(None, description="When was this included in plan generation?")
    
    # Include related data
    original_order: Optional[OrderMaster] = None
    created_by: Optional[UserMaster] = None

    class Config:
        from_attributes = True

# Inventory Master Schemas
class InventoryMasterBase(BaseModel):
    paper_id: UUID
    width_inches: float = Field(..., gt=0)
    weight_kg: float = Field(..., gt=0)
    roll_type: RollType = Field(..., description="Roll type: jumbo, 118, or cut")
    location: Optional[str] = Field(None, max_length=100)
    qr_code: Optional[str] = Field(None, max_length=255)
    barcode_id: Optional[str] = Field(None, description="Human-readable barcode ID")
    production_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Jumbo roll hierarchy fields
    parent_jumbo_id: Optional[UUID] = Field(None, description="Parent jumbo roll ID")
    parent_118_roll_id: Optional[UUID] = Field(None, description="Parent 118 inch roll ID")
    roll_sequence: Optional[int] = Field(None, description="Position within jumbo (1, 2, 3)")
    individual_roll_number: Optional[int] = Field(None, description="From optimization algorithm")
    
    # Wastage tracking fields
    is_wastage_roll: Optional[bool] = Field(False, description="Indicates if this is a wastage roll")
    wastage_source_order_id: Optional[UUID] = Field(None, description="Original order that generated this wastage")
    wastage_source_plan_id: Optional[UUID] = Field(None, description="Plan that created this wastage")

class InventoryMasterCreate(InventoryMasterBase):
    created_by_id: UUID

class InventoryMasterUpdate(BaseModel):
    location: Optional[str] = Field(None, max_length=100)
    status: Optional[InventoryStatus] = None
    allocated_to_order_id: Optional[UUID] = None

class InventoryMaster(InventoryMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable inventory ID (e.g., INV-001)")
    status: InventoryStatus
    allocated_to_order_id: Optional[UUID] = None
    created_by_id: UUID
    created_at: datetime
    
    # Wastage tracking fields (included in response)
    is_wastage_roll: bool = Field(False, description="Indicates if this is a wastage roll")
    wastage_source_order_id: Optional[UUID] = Field(None, description="Original order that generated this wastage")
    wastage_source_plan_id: Optional[UUID] = Field(None, description="Plan that created this wastage")
    
    # Include related data
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# Plan Master Schemas
class PlanMasterBase(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    cut_pattern: List[Dict[str, Any]] = Field(..., description="JSON array of cutting pattern")
    expected_waste_percentage: float = Field(..., ge=0, le=100)

class PlanMasterCreate(PlanMasterBase):
    created_by_id: UUID
    order_ids: List[UUID] = Field(..., min_items=1)
    inventory_ids: Optional[List[UUID]] = Field(default_factory=list, description="Optional inventory IDs for plan")
    pending_orders: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Pending orders from algorithm")
    wastage_allocations: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Wastage allocations calculated during planning")

class PlanMasterUpdate(BaseModel):
    status: Optional[PlanStatus] = None
    actual_waste_percentage: Optional[float] = Field(None, ge=0, le=100)

class PlanMaster(PlanMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable plan ID (e.g., PLN-2025-001)")
    status: PlanStatus
    actual_waste_percentage: Optional[float] = None
    created_by_id: UUID
    created_at: datetime
    executed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @field_validator('cut_pattern', mode='before')
    @classmethod
    def parse_cut_pattern(cls, v):
        """Parse cut_pattern from JSON string if needed"""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return []
        return v

    class Config:
        from_attributes = True

# Plan Order Item Schema
class PlanOrderItem(BaseModel):
    """Schema for order items linked to a plan with estimated weights"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable order item ID (e.g., ORI-001)")
    order_id: UUID
    width_inches: float
    quantity_rolls: int
    estimated_weight_kg: float = Field(..., description="Estimated weight based on paper specs")
    gsm: int
    bf: float
    shade: str
    
    class Config:
        from_attributes = True

# Production Order Master Schemas
class ProductionOrderMasterBase(BaseModel):
    paper_id: UUID
    quantity: int = Field(default=1, gt=0)
    priority: Priority = Field(default=Priority.NORMAL)

class ProductionOrderMasterCreate(ProductionOrderMasterBase):
    created_by_id: UUID

class ProductionOrderMasterUpdate(BaseModel):
    priority: Optional[Priority] = None
    status: Optional[ProductionOrderStatus] = None

class ProductionOrderMaster(ProductionOrderMasterBase):
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable production order ID (e.g., PRO-001)")
    status: ProductionOrderStatus
    created_by_id: UUID
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Include related data
    paper: Optional[PaperMaster] = None

    class Config:
        from_attributes = True

# ============================================================================
# CUTTING OPTIMIZER SCHEMAS - NEW FLOW: 3-input/4-output
# ============================================================================

class OptimizerInventoryItem(BaseModel):
    """Individual inventory item for optimization input"""
    id: Optional[str] = None
    width: float = Field(..., gt=0, description="Width in inches")
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    weight: Optional[float] = Field(None, ge=0)
    location: Optional[str] = None

class OptimizerInput(BaseModel):
    """NEW FLOW: Complete input for 3-input optimization"""
    orders: List[Dict[str, Any]] = Field(..., min_items=1, description="New orders to process")
    pending_orders: List[Dict[str, Any]] = Field(default_factory=list, description="Pending orders from previous cycles")
    available_inventory: List[OptimizerInventoryItem] = Field(default_factory=list, description="Available 20-25\" waste rolls")

class CutRollGenerated(BaseModel):
    """Individual cut roll that was generated"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    source: str = Field(..., description="'inventory' or 'cutting'")
    inventory_id: Optional[str] = None
    jumbo_number: Optional[int] = None
    trim_left: Optional[float] = None
    
    # Enhanced jumbo roll hierarchy fields
    jumbo_roll_id: Optional[str] = Field(None, description="Virtual jumbo roll ID")
    jumbo_roll_frontend_id: Optional[str] = Field(None, description="Human-readable jumbo ID (e.g., JR-001)")
    parent_118_roll_id: Optional[str] = Field(None, description="Parent 118 inch roll ID")
    roll_sequence: Optional[int] = Field(None, description="Position within jumbo (1, 2, 3)")
    individual_roll_number: Optional[int] = Field(None, description="118 roll number from optimization")

class PendingOrderOutput(BaseModel):
    """Pending order that couldn't be fulfilled"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    reason: str = Field(..., description="Reason why it's pending")

class InventoryRemaining(BaseModel):
    """Inventory item remaining after optimization"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    source: str = Field(..., description="'waste', 'unused_inventory'")
    inventory_id: Optional[str] = None
    from_jumbo: Optional[int] = None

class OptimizerOutput(BaseModel):
    """NEW FLOW: Complete output for 4-output optimization"""
    cut_rolls_generated: List[CutRollGenerated] = Field(..., description="Rolls that can be fulfilled")
    jumbo_rolls_needed: int = Field(..., ge=0, description="Number of jumbo rolls to procure")
    pending_orders: List[PendingOrderOutput] = Field(..., description="Orders that cannot be fulfilled")
    inventory_remaining: List[InventoryRemaining] = Field(..., description="20-25\" waste rolls for future use")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")
    
    # Enhanced jumbo roll hierarchy information
    jumbo_roll_details: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Jumbo roll hierarchy details")

class CuttingOptimizationRequest(BaseModel):
    """Request for cutting optimization with order IDs - UPDATED for new flow"""
    order_ids: List[UUID] = Field(..., min_items=1)
    include_pending: bool = Field(default=True, description="Include pending orders in optimization")
    include_inventory: bool = Field(default=True, description="Include available waste inventory")
    interactive: bool = Field(default=False, description="Enable interactive trim decisions")

class CreatePlanRequest(BaseModel):
    """Request to create a cutting plan from order IDs"""
    order_ids: List[str] = Field(..., min_items=1, description="List of order IDs to include in plan")
    created_by_id: str = Field(..., description="ID of user creating the plan")
    plan_name: Optional[str] = Field(None, description="Optional name for the plan")

class CuttingPattern(BaseModel):
    """A single cutting pattern result"""
    rolls: List[Dict[str, Any]] = Field(..., description="Rolls in this pattern")
    trim_left: float = Field(..., ge=0, description="Trim left in inches")
    waste_percentage: float = Field(..., ge=0, le=100, description="Waste percentage")
    paper_spec: Dict[str, Any] = Field(..., description="Paper specification used")

class CuttingOptimizationResult(BaseModel):
    """Result of cutting optimization"""
    jumbo_rolls_used: List[CuttingPattern] = Field(..., description="Cutting patterns generated")
    pending_orders: List[PendingOrderMaster] = Field(default_factory=list, description="Orders that couldn't be fulfilled")
    high_trim_approved: List[Dict[str, Any]] = Field(default_factory=list, description="High trim patterns approved")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")

# ============================================================================
# WORKFLOW SCHEMAS - For workflow operations
# ============================================================================

class WorkflowProcessRequest(BaseModel):
    """NEW FLOW: Request to process multiple orders through workflow"""
    order_ids: List[UUID] = Field(..., min_items=1)
    jumbo_roll_width: int = Field(default=118, ge=50, le=300, description="Jumbo roll width in inches")
    auto_approve_high_trim: bool = Field(default=False, description="Auto-approve high trim patterns")
    skip_inventory_check: bool = Field(default=True, description="NEW FLOW: Skip inventory checking, go directly to planning")

class WorkflowResult(BaseModel):
    """NEW FLOW: Result of workflow processing with 4 outputs"""
    status: str = Field(..., description="Overall workflow status")
    cut_rolls_generated: List[CutRollGenerated] = Field(..., description="Rolls ready for fulfillment")
    jumbo_rolls_needed: int = Field(..., ge=0, description="Jumbo rolls to procure")
    pending_orders_created: List[PendingOrderOutput] = Field(..., description="New pending orders created")
    inventory_created: List[InventoryRemaining] = Field(..., description="Waste inventory created")
    orders_updated: List[str] = Field(..., description="Order IDs that were updated")
    plans_created: List[str] = Field(..., description="Plan IDs that were created")
    production_orders_created: List[str] = Field(..., description="Production order IDs created")

class WorkflowStatus(BaseModel):
    """Current workflow status"""
    orders: Dict[str, int] = Field(..., description="Order counts by status")
    pending_items: Dict[str, int] = Field(..., description="Pending item statistics")
    inventory: Dict[str, int] = Field(..., description="Inventory statistics")
    production: Dict[str, int] = Field(..., description="Production statistics")
    recommendations: List[str] = Field(default_factory=list, description="Workflow recommendations")

# ============================================================================
# RESPONSE SCHEMAS - Common response formats
# ============================================================================

class SuccessResponse(BaseModel):
    """Standard success response"""
    message: str
    data: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None

class PaginatedResponse(BaseModel):
    """Paginated response wrapper"""
    items: List[Any]
    total: int
    page: int
    size: int
    pages: int


# ============================================================================
# ADDITIONAL SCHEMAS FOR NEW ENDPOINTS
# ============================================================================

class UserLogin(BaseModel):
    """Schema for user login request"""
    username: str
    password: str

class CuttingPlanRequestItem(BaseModel):
    """Individual item in cutting plan request"""
    width: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str
    min_length: int = Field(default=1600, gt=0)

class CuttingPlanRequest(BaseModel):
    """Schema for cutting plan generation request"""
    order_requirements: List[CuttingPlanRequestItem]
    pending_orders: Optional[List[Dict[str, Any]]] = None
    available_inventory: Optional[List[Dict[str, Any]]] = None

class CuttingPlanWithSelectionRequest(CuttingPlanRequest):
    """Schema for cutting plan with selection criteria"""
    selection_criteria: Optional[Dict[str, Any]] = None

class QRWeightUpdate(BaseModel):
    """Schema for updating weight via QR code - status automatically set to 'available'"""
    qr_code: str
    weight_kg: float = Field(..., gt=0)
    location: Optional[str] = None

class BarcodeWeightUpdate(BaseModel):
    """Schema for updating weight via barcode - status automatically set to 'available'"""
    barcode_id: str
    weight_kg: float = Field(..., gt=0)
    location: Optional[str] = None

class QRGenerateRequest(BaseModel):
    """Schema for generating QR code"""
    inventory_id: Optional[UUID] = None

class CutRollSelection(BaseModel):
    """Individual cut roll selection"""
    paper_id: UUID
    width_inches: float
    qr_code: Optional[str] = None
    cutting_pattern: Optional[str] = None

class CutRollSelectionRequest(BaseModel):
    """Schema for selecting cut rolls for production"""
    plan_id: Optional[UUID] = None
    selected_rolls: List[CutRollSelection]
    created_by_id: UUID

class PlanStatusUpdate(BaseModel):
    """Schema for updating plan status"""
    status: str
    actual_waste_percentage: Optional[float] = None

class PlanInventoryLinkRequest(BaseModel):
    """Schema for linking inventory to plans"""
    inventory_ids: List[UUID]

class InventoryStatusUpdate(BaseModel):
    """Schema for updating inventory status"""
    new_status: str
    location: Optional[str] = None

# ============================================================================
# DISPATCH SCHEMAS
# ============================================================================

class DispatchFormData(BaseModel):
    """Schema for dispatch form data"""
    vehicle_number: str = Field(..., max_length=50)
    driver_name: str = Field(..., max_length=255)
    driver_mobile: str = Field(..., max_length=20)
    payment_type: str = Field(default="bill")  # bill/cash
    dispatch_date: datetime = Field(default_factory=datetime.utcnow)
    dispatch_number: str = Field(..., max_length=100)
    reference_number: Optional[str] = Field(None, max_length=100)
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    inventory_ids: List[UUID] = Field(..., min_items=1)
    created_by_id: UUID

class DispatchRecordCreate(BaseModel):
    """Schema for creating dispatch record"""
    vehicle_number: str
    driver_name: str
    driver_mobile: str
    payment_type: str
    dispatch_date: datetime
    dispatch_number: str
    reference_number: Optional[str] = None
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    total_items: int
    total_weight_kg: float
    created_by_id: UUID

class DispatchItem(BaseModel):
    """Schema for dispatch item"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable dispatch item ID (e.g., DIT-001)")
    dispatch_record_id: UUID
    inventory_id: UUID
    qr_code: str
    width_inches: float
    weight_kg: float
    paper_spec: str
    status: str
    dispatched_at: datetime
    
    class Config:
        from_attributes = True

class DispatchRecord(BaseModel):
    """Schema for dispatch record with items"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable dispatch record ID (e.g., DSP-001)")
    vehicle_number: str
    driver_name: str
    driver_mobile: str
    payment_type: str
    dispatch_date: datetime
    dispatch_number: str
    reference_number: Optional[str] = None
    client_id: UUID
    primary_order_id: Optional[UUID] = None
    order_date: Optional[datetime] = None
    status: str
    total_items: int
    total_weight_kg: float
    created_by_id: UUID
    created_at: datetime
    delivered_at: Optional[datetime] = None
    
    # Include related data
    client: Optional[ClientMaster] = None
    primary_order: Optional[OrderMaster] = None
    created_by: Optional[UserMaster] = None
    dispatch_items: List[DispatchItem] = Field(default_factory=list)
    
    class Config:
        from_attributes = True

# ============================================================================
# PRODUCTION START SCHEMAS - NEW FLOW
# ============================================================================

class SelectedCutRoll(BaseModel):
    """Individual cut roll selected for production"""
    paper_id: Optional[str] = Field(None, description="Paper ID for this cut roll - can be resolved from specs for pending orders")
    width_inches: float = Field(..., gt=0, description="Width in inches")
    qr_code: str = Field(..., description="QR code for tracking")
    gsm: int = Field(..., gt=0)
    bf: float = Field(..., gt=0)
    shade: str = Field(..., max_length=50)
    individual_roll_number: Optional[int] = Field(None, description="Roll number within jumbo")
    trim_left: Optional[float] = Field(None, ge=0, description="Trim left in inches")
    order_id: Optional[str] = Field(None, description="Source order ID")
    # CRITICAL: Add source tracking fields for pending order resolution
    source_type: Optional[str] = Field(None, description="Source type: 'regular_order', 'pending_order', or 'manual_cut'")
    source_pending_id: Optional[str] = Field(None, description="ID of source pending order if applicable")
    # Manual cut specific fields
    is_manual_cut: Optional[bool] = Field(None, description="True if this is a manual cut")
    manual_cut_client_id: Optional[str] = Field(None, description="Client ID for manual cuts")
    manual_cut_client_name: Optional[str] = Field(None, description="Client name for manual cuts")
    description: Optional[str] = Field(None, description="Description for manual cuts")

class WastageData(BaseModel):
    """Wastage data for tracking waste material"""
    width_inches: float = Field(..., description="Width of waste material in inches")
    paper_id: str = Field(..., description="Paper master ID")
    gsm: int = Field(..., ge=50, le=500, description="Paper GSM")
    bf: float = Field(..., ge=10, le=50, description="Paper BF")
    shade: str = Field(..., description="Paper shade")
    individual_roll_number: Optional[int] = Field(None, description="Source 118 roll number")
    source_plan_id: str = Field(..., description="Source plan ID")
    source_jumbo_roll_id: Optional[str] = Field(None, description="Source jumbo roll ID")
    notes: Optional[str] = Field(None, description="Additional notes")

class StartProductionRequest(BaseModel):
    """Request to start production with comprehensive roll handling"""
    selected_cut_rolls: List[SelectedCutRoll] = Field(..., min_items=1, description="Cut rolls selected for production")
    all_available_cuts: List[SelectedCutRoll] = Field(..., description="All cuts that were available for selection")
    wastage_data: List[WastageData] = Field(default=[], description="Wastage data for 9-21 inch waste")
    added_rolls_data: Dict[str, List[Dict[str, Any]]] = Field(default={}, description="Added rolls data for partial jumbo completion by jumbo_id")
    created_by_id: str = Field(..., description="ID of user starting production")
    jumbo_roll_width: int = Field(default=118, ge=50, le=300, description="Dynamic jumbo roll width in inches")

# ============================================================================
# PENDING PRODUCTION SCHEMAS - NEW PENDING TO PRODUCTION FLOW
# ============================================================================

class SelectedSuggestion(BaseModel):
    """Individual suggestion selected for production from pending orders"""
    suggestion_id: str = Field(..., description="Unique suggestion ID")
    paper_specs: Dict[str, Any] = Field(..., description="Paper specifications (gsm, shade, bf)")
    rolls: List[Dict[str, Any]] = Field(..., description="Roll details from suggestion")
    target_width: float = Field(..., gt=0, description="Target width for this suggestion")
    pending_order_ids: List[str] = Field(..., description="List of pending order IDs this suggestion uses")

class StartPendingProductionRequest(BaseModel):
    """Request to start production from selected pending order suggestions"""
    selected_suggestions: List[SelectedSuggestion] = Field(..., min_items=1, description="Selected suggestions for production")
    created_by_id: str = Field(..., description="ID of user starting production")
    jumbo_roll_width: int = Field(default=118, ge=50, le=300, description="Dynamic jumbo roll width in inches")

class ProductionStartSummary(BaseModel):
    """Summary of production start operation"""
    orders_updated: int = Field(..., ge=0)
    order_items_updated: int = Field(..., ge=0)
    pending_orders_resolved: int = Field(..., ge=0, description="Number of pending orders processed (supports partial fulfillment - only fully resolved when quantity_pending=0)")
    inventory_created: int = Field(..., ge=0)
    pending_orders_created_phase2: int = Field(default=0, ge=0, description="Number of PHASE 2 pending orders created from unselected cuts")
    jumbo_rolls_created: int = Field(default=0, ge=0, description="Number of virtual jumbo rolls created")
    intermediate_118_rolls_created: int = Field(default=0, ge=0, description="Number of intermediate 118\" rolls created")

class InventoryDetail(BaseModel):
    """Inventory item details for production response"""
    id: str
    barcode_id: str
    qr_code: str
    width_inches: float
    paper_id: str
    status: str
    created_at: Optional[str] = None

class StartProductionResponse(BaseModel):
    """Response from start production operation"""
    plan_id: str
    status: str
    executed_at: Optional[str] = None
    summary: ProductionStartSummary
    details: Dict[str, List[str]]
    created_inventory_details: List[InventoryDetail] = Field(default_factory=list)
    message: str

# ============================================================================
# WASTAGE INVENTORY SCHEMAS
# ============================================================================

class WastageInventoryCreate(BaseModel):
    """Schema for creating manual wastage inventory item"""
    # Required fields
    width_inches: float = Field(...)
    paper_id: UUID = Field(..., description="Paper master ID")

    # Optional fields
    weight_kg: Optional[float] = Field(default=0.0, ge=0, description="Weight in kg (can be set later via QR scan)")
    reel_no: Optional[str] = Field(None, max_length=50, description="Optional reel number for identification")
    status: Optional[str] = Field(default="available", description="Status: available, used, damaged")
    location: Optional[str] = Field(default="WASTE_STORAGE", description="Storage location")
    notes: Optional[str] = Field(None, max_length=500, description="Additional notes for manual identification")

    # Optional source tracking (for manual entries that know their source)
    source_plan_id: Optional[UUID] = Field(None, description="Source plan ID (if known)")
    source_jumbo_roll_id: Optional[UUID] = Field(None, description="Source jumbo roll ID (if known)")
    individual_roll_number: Optional[int] = Field(None, ge=1, description="Source 118 roll number (if known)")

class WastageInventory(BaseModel):
    """Schema for wastage inventory item"""
    id: UUID
    frontend_id: Optional[str] = Field(None, description="Human-readable wastage ID (e.g., WS-00001)")
    barcode_id: Optional[str] = Field(None, description="Barcode ID (e.g., WSB-00001)")

    # Wastage details
    width_inches: float = Field(..., description="Width of waste material in inches")
    paper_id: UUID = Field(..., description="Paper master ID")
    weight_kg: float = Field(default=0.0, description="Weight in kg")
    reel_no: Optional[str] = Field(None, description="Optional reel number for identification")

    # Source information
    source_plan_id: Optional[UUID] = Field(None, description="Source plan ID")
    source_jumbo_roll_id: Optional[UUID] = Field(None, description="Source jumbo roll ID")
    individual_roll_number: Optional[int] = Field(None, description="Source 118 roll number")

    # Status and tracking
    status: str = Field(default="available", description="Status: available, used, damaged")
    location: Optional[str] = Field(None, description="Storage location")

    # Audit fields
    created_at: datetime
    created_by_id: Optional[UUID] = Field(None, description="Creator user ID")
    updated_at: Optional[datetime] = Field(None, description="Last update time")

    # Notes
    notes: Optional[str] = Field(None, description="Additional notes")

    # Relationships (optional, loaded when needed)
    paper: Optional[PaperMaster] = None
    created_by: Optional[UserMaster] = None

    class Config:
        from_attributes = True


class PaginatedWastageResponse(BaseModel):
    """Paginated response for wastage inventory"""
    items: List[WastageInventory]
    total: int
    page: int
    per_page: int
    total_pages: int


# ============================================================================
# INVENTORY ITEMS SCHEMAS - For imported stock data
# ============================================================================

class InventoryItemBase(BaseModel):
    """Base schema for inventory items"""
    sno_from_file: Optional[int] = Field(None, description="Serial number from file")
    reel_no: Optional[str] = Field(None, description="Reel number")
    gsm: Optional[int] = Field(None, description="GSM value")
    bf: Optional[int] = Field(None, description="BF value")
    size: Optional[str] = Field(None, description="Size as text")
    weight_kg: Optional[float] = Field(None, description="Weight in kg")
    grade: Optional[str] = Field(None, description="Grade")
    stock_date: Optional[datetime] = Field(None, description="Stock date")

class InventoryItemCreate(InventoryItemBase):
    """Schema for creating inventory items"""
    pass

class InventoryItemUpdate(InventoryItemBase):
    """Schema for updating inventory items"""
    pass

class InventoryItem(InventoryItemBase):
    """Full inventory item schema with all fields"""
    stock_id: int = Field(..., description="Primary key")
    record_imported_at: datetime = Field(..., description="When record was imported")
    
    class Config:
        from_attributes = True

class PaginatedInventoryItemsResponse(BaseModel):
    """Paginated response for inventory items"""
    items: List[InventoryItem]
    total: int
    page: int
    per_page: int
    total_pages: int

# ============================================================================
# PENDING ORDER ALLOCATION SCHEMAS
# ============================================================================

class PendingOrderAllocationRequest(BaseModel):
    """Schema for allocating pending order to an order"""
    target_order_id: UUID = Field(..., description="Order ID to allocate pending order to")
    quantity_to_transfer: int = Field(..., gt=0, description="Quantity to transfer")
    created_by_id: UUID = Field(..., description="User performing the allocation")

class PendingOrderTransferRequest(BaseModel):
    """Schema for transferring pending order between orders"""
    source_order_id: UUID = Field(..., description="Source order ID")
    target_order_id: UUID = Field(..., description="Target order ID")
    quantity_to_transfer: int = Field(..., gt=0, description="Quantity to transfer")
    created_by_id: UUID = Field(..., description="User performing the transfer")

class AvailableOrder(BaseModel):
    """Schema for orders available for pending order allocation"""
    id: UUID
    frontend_id: Optional[str] = None
    client_id: UUID
    client_name: str
    status: str
    priority: str
    payment_type: str
    delivery_date: Optional[datetime] = None
    created_at: datetime
    has_matching_paper: bool = Field(..., description="Whether order has items with matching paper specs")
    matching_items_count: int = Field(default=0, description="Number of order items with matching paper specs")

class PendingOrderAllocationResponse(BaseModel):
    """Response for pending order allocation operations"""
    message: str
    pending_order_item: PendingOrderItem
    created_order_item: Optional[OrderItem] = None
    updated_order_item: Optional[OrderItem] = None
    allocation_details: Dict[str, Any] = Field(default_factory=dict)

