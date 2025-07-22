from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID
from decimal import Decimal

# User schemas
class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    role: str = Field(default="operator", pattern="^(operator|manager|admin)$")

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class UserUpdate(BaseModel):
    password: Optional[str] = Field(None, min_length=6)
    role: Optional[str] = Field(None, pattern="^(operator|manager|admin)$")

class User(UserBase):
    id: UUID
    created_at: datetime
    last_login: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

# User session schemas
class UserSessionCreate(BaseModel):
    user_id: UUID
    expires_at: datetime

class UserSession(BaseModel):
    id: UUID
    user_id: UUID
    session_token: str
    created_at: datetime
    expires_at: datetime
    is_active: bool
    
    model_config = ConfigDict(from_attributes=True)

# Parsed message schemas
class ParsedMessageBase(BaseModel):
    raw_message: str = Field(..., min_length=1)

class ParsedMessageCreate(ParsedMessageBase):
    pass

class ParsedMessageUpdate(BaseModel):
    parsed_json: Optional[str] = None
    parsing_confidence: Optional[Decimal] = Field(None, ge=0, le=100)
    parsing_status: Optional[str] = Field(None, pattern="^(pending|success|failed)$")

class ParsedMessage(ParsedMessageBase):
    id: UUID
    received_at: datetime
    parsed_json: Optional[str] = None
    parsing_confidence: Optional[Decimal] = None
    parsing_status: str
    created_by: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

# Order schemas
class OrderBase(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    width_inches: int = Field(..., gt=0, le=200)
    gsm: int = Field(..., gt=0, le=1000)
    bf: Decimal = Field(..., ge=0, le=100)
    shade: str = Field(..., min_length=1, max_length=50)
    quantity_rolls: int = Field(..., gt=0)
    quantity_tons: Optional[Decimal] = Field(None, ge=0)

class OrderCreate(OrderBase):
    source_message_id: Optional[UUID] = None

class OrderUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(pending|processing|completed|cancelled)$")
    quantity_rolls: Optional[int] = Field(None, gt=0)
    quantity_tons: Optional[Decimal] = Field(None, ge=0)

class Order(OrderBase):
    id: UUID
    status: str
    source_message_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# Jumbo roll schemas
class JumboRollBase(BaseModel):
    width_inches: int = Field(default=119, gt=0, le=200)
    weight_kg: int = Field(default=4500, gt=0)
    gsm: int = Field(..., gt=0, le=1000)
    bf: Decimal = Field(..., ge=0, le=100)
    shade: str = Field(..., min_length=1, max_length=50)
    production_date: datetime

class JumboRollCreate(JumboRollBase):
    pass

class JumboRollUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(available|cutting|used)$")

class JumboRoll(JumboRollBase):
    id: UUID
    status: str
    created_by: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

# Cut roll schemas
class CutRollBase(BaseModel):
    width_inches: int = Field(..., gt=0, le=200)
    gsm: int = Field(..., gt=0, le=1000)
    bf: Decimal = Field(..., ge=0, le=100)
    shade: str = Field(..., min_length=1, max_length=50)
    weight_kg: Optional[Decimal] = Field(None, ge=0)

class CutRollCreate(CutRollBase):
    jumbo_roll_id: UUID
    order_id: Optional[UUID] = None

class CutRollUpdate(BaseModel):
    weight_kg: Optional[Decimal] = Field(None, ge=0)
    status: Optional[str] = Field(None, pattern="^(cut|weighed|allocated|used)$")

class CutRoll(CutRollBase):
    id: UUID
    jumbo_roll_id: UUID
    qr_code: str
    cut_date: datetime
    status: str
    order_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

# Inventory schemas
class InventoryItemBase(BaseModel):
    location: Optional[str] = Field(None, max_length=100)

class InventoryItemCreate(InventoryItemBase):
    roll_id: UUID

class InventoryItemUpdate(BaseModel):
    location: Optional[str] = Field(None, max_length=100)
    allocated_to_order: Optional[UUID] = None

class InventoryItem(InventoryItemBase):
    id: UUID
    roll_id: UUID
    allocated_to_order: Optional[UUID] = None
    last_updated: datetime
    
    model_config = ConfigDict(from_attributes=True)

# Cutting plan schemas
class CuttingPlanBase(BaseModel):
    plan_data: str  # JSON string containing cutting plan details
    expected_waste_percentage: Optional[Decimal] = Field(None, ge=0, le=100)

class CuttingPlanCreate(CuttingPlanBase):
    jumbo_roll_id: UUID

class CuttingPlanUpdate(BaseModel):
    status: Optional[str] = Field(None, pattern="^(planned|approved|executing|completed)$")
    plan_data: Optional[str] = None
    expected_waste_percentage: Optional[Decimal] = Field(None, ge=0, le=100)

class CuttingPlan(CuttingPlanBase):
    id: UUID
    jumbo_roll_id: UUID
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

# Response schemas for complex queries
class OrderWithDetails(Order):
    source_message: Optional[ParsedMessage] = None
    cut_rolls: List[CutRoll] = []

class CutRollWithInventory(CutRoll):
    inventory_item: Optional[InventoryItem] = None

class InventoryItemWithRoll(InventoryItem):
    roll: CutRoll

# Filter schemas for search endpoints
class OrderFilter(BaseModel):
    customer_name: Optional[str] = None
    status: Optional[str] = None
    width_inches: Optional[int] = None
    gsm: Optional[int] = None
    bf: Optional[Decimal] = None
    shade: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

class InventoryFilter(BaseModel):
    width_inches: Optional[int] = None
    gsm: Optional[int] = None
    bf: Optional[Decimal] = None
    shade: Optional[str] = None
    status: Optional[str] = None
    allocated: Optional[bool] = None
    location: Optional[str] = None

# Response schemas for complex queries
class OrderWithDetails(Order):
    source_message: Optional[ParsedMessage] = None
    cut_rolls: List["CutRoll"] = []
    
    model_config = ConfigDict(from_attributes=True)