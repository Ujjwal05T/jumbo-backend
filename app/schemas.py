from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from uuid import UUID
from pydantic import EmailStr

# Shared properties
class OrderBase(BaseModel):
    customer_name: str
    width_inches: int
    gsm: int
    bf: float
    shade: str
    quantity_rolls: int
    quantity_tons: Optional[float] = None
    status: Optional[str] = "pending"  # pending, processing, ready_for_delivery, in_transit, delivered, cancelled
    source_message_id: Optional[UUID] = None
    target_delivery_date: Optional[datetime] = None
    actual_delivery_date: Optional[datetime] = None
    delivery_notes: Optional[str] = None

# Delivery update schema
class OrderDeliveryUpdate(BaseModel):
    status: str = Field(..., description="New status for the order", pattern=r"^(pending|processing|ready_for_delivery|in_transit|delivered|cancelled)$")
    actual_delivery_date: Optional[datetime] = Field(None, description="Actual delivery date. If not provided, will be set to current time when status is 'delivered'")
    delivery_notes: Optional[str] = Field(None, max_length=1000, description="Optional notes about the delivery")

class OrderCreate(OrderBase):
    pass

class OrderUpdate(BaseModel):
    status: Optional[str] = None
    quantity_rolls: Optional[int] = None
    quantity_tons: Optional[float] = None

class Order(OrderBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Jumbo Roll schemas
class JumboRollBase(BaseModel):
    roll_number: str
    width_inches: int
    gsm: int
    bf: float
    shade: str
    weight_kg: float
    is_used: bool = False

class JumboRollCreate(JumboRollBase):
    pass

class JumboRollUpdate(BaseModel):
    is_used: Optional[bool] = None

class JumboRoll(JumboRollBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Cut Roll schemas
class CutRollBase(BaseModel):
    roll_number: str
    width_inches: int
    gsm: int
    bf: float
    shade: str
    weight_kg: float
    qr_code_path: Optional[str] = None
    order_id: Optional[UUID] = None

class CutRollCreate(CutRollBase):
    pass

class CutRollUpdate(BaseModel):
    weight_kg: Optional[float] = None
    status: Optional[str] = None
    order_id: Optional[UUID] = None

class CutRoll(CutRollBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Parsed Message schemas
class ParsedMessageBase(BaseModel):
    raw_message: str
    parsed_json: Optional[Dict[str, Any]] = None
    parsing_confidence: Optional[float] = None

class ParsedMessageCreate(ParsedMessageBase):
    pass

class ParsedMessageUpdate(BaseModel):
    parsed_json: Optional[Dict[str, Any]] = None
    parsing_confidence: Optional[float] = None
    parsing_status: Optional[str] = None

class ParsedMessage(ParsedMessageBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Inventory schemas
class InventoryItemBase(BaseModel):
    roll_id: UUID
    location: Optional[str] = None
    allocated_to_order: Optional[UUID] = None

class InventoryItemCreate(InventoryItemBase):
    pass

class InventoryItemUpdate(BaseModel):
    location: Optional[str] = None
    allocated_to_order: Optional[UUID] = None

class InventoryItem(InventoryItemBase):
    id: UUID
    created_at: datetime
    last_updated: datetime

    class Config:
        from_attributes = True

# Inventory log schema
class InventoryLogBase(BaseModel):
    roll_id: UUID = Field(..., description="ID of the cut roll")
    order_id: Optional[UUID] = Field(None, description="ID of the associated order, if any")
    action: str = Field(..., description="Action performed (e.g., created, allocated, delivered)", max_length=50)
    previous_status: Optional[str] = Field(None, max_length=50, description="Previous status of the roll")
    new_status: str = Field(..., max_length=50, description="New status after the action")
    notes: Optional[str] = Field(None, max_length=1000, description="Additional details about the action")

class InventoryLogCreate(InventoryLogBase):
    created_by_id: UUID = Field(..., description="ID of the user performing the action")

class InventoryLog(InventoryLogBase):
    id: UUID
    created_at: datetime
    created_by_id: UUID

    class Config:
        from_attributes = True

# Cutting Plan schemas
class CuttingPlanBase(BaseModel):
    order_id: UUID
    jumbo_roll_id: UUID
    cut_pattern: List[Dict[str, Any]]
    expected_waste_percentage: float = Field(..., ge=0, le=100)
    status: str
    notes: Optional[str] = None

class CuttingPlanCreate(CuttingPlanBase):
    pass

class CuttingPlanUpdate(BaseModel):
    status: Optional[str] = None
    actual_waste_percentage: Optional[float] = Field(None, ge=0, le=100)
    notes: Optional[str] = None

class CuttingPlanInDBBase(CuttingPlanBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    created_by_id: UUID
    actual_waste_percentage: Optional[float] = None
    completed_at: Optional[datetime] = None

    class Config:
        orm_mode = True

class CuttingPlan(CuttingPlanInDBBase):
    pass

class CuttingPlanDetail(BaseModel):
    plan: CuttingPlan
    cut_rolls: List[Any] = []
    jumbo_roll: Any
    order: Any

# Cutting Optimization Request/Response schemas
class RollSpec(BaseModel):
    """Specification for a roll to be cut."""
    width: int = Field(..., gt=0, description="Width of the roll in inches")
    quantity: int = Field(..., gt=0, description="Number of rolls needed")
    gsm: int = Field(..., gt=0, description="Grams per square meter")
    bf: float = Field(..., gt=0, description="Burst factor")
    shade: str = Field(..., description="Shade/color of the paper")
    min_length: Optional[int] = Field(None, gt=0, description="Minimum length required in meters")

class InventoryRollSpec(RollSpec):
    """Roll specification with inventory-specific fields."""
    id: UUID = Field(..., description="Inventory ID of the roll")
    status: str = Field(..., description="Current status of the roll")
    length: Optional[float] = Field(None, description="Length of the roll in meters")

class CuttingPattern(BaseModel):
    """A single cutting pattern for a jumbo roll."""
    rolls: List[Dict[str, Any]] = Field(..., description="List of rolls in this pattern")
    waste_percentage: float = Field(..., ge=0, le=100, description="Waste percentage for this pattern")
    waste_inches: float = Field(..., ge=0, description="Waste in inches for this pattern")

class OptimizedCuttingPlan(BaseModel):
    """Response model for an optimized cutting plan."""
    patterns: List[CuttingPattern] = Field(..., description="List of cutting patterns")
    total_rolls_needed: int = Field(..., ge=0, description="Total number of jumbo rolls needed")
    total_waste_percentage: float = Field(..., ge=0, le=100, description="Total waste percentage")
    total_waste_inches: float = Field(..., ge=0, description="Total waste in inches")
    fulfilled_orders: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of orders fulfilled from inventory"
    )
    unfulfilled_orders: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of orders that couldn't be fulfilled from inventory"
    )

class OrderCuttingPlanRequest(BaseModel):
    """Request model for generating a cutting plan from order IDs."""
    order_ids: List[UUID] = Field(..., min_items=1, description="List of order IDs to include in the plan")
    consider_inventory: bool = Field(
        True,
        description="Whether to consider existing inventory when generating the plan"
    )
    optimize_for: str = Field(
        "waste",
        pattern=r"^(waste|speed|material_usage)$",
        description="Optimization strategy: 'waste', 'speed', or 'material_usage'"
    )

class CustomCuttingPlanRequest(BaseModel):
    """Request model for generating a cutting plan from custom roll specifications."""
    rolls: List[RollSpec] = Field(..., min_items=1, description="List of roll specifications to include in the plan")
    available_inventory: Optional[List[InventoryRollSpec]] = Field(
        None,
        description="Optional list of available inventory to consider"
    )
    jumbo_roll_width: int = Field(119, gt=0, description="Width of jumbo rolls in inches")
    consider_standard_sizes: bool = Field(
        True,
        description="Whether to consider standard sizes when optimizing cuts"
    )
    strict_matching: bool = Field(
        True,
        description="If True, requires exact GSM, BF, and Shade matches when using inventory"
    )

# User schemas
class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserLogin(UserBase):
    password: str

class User(UserBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# Simple response schemas
class AuthResponse(BaseModel):
    status: str
    username: str

# Token schemas (for future JWT implementation if needed)
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None