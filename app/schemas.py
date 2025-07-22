from typing import List, Optional, Dict, Any
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
    status: Optional[str] = "pending"
    source_message_id: Optional[UUID] = None

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

# Cutting Plan schemas
class CuttingPlanBase(BaseModel):
    jumbo_roll_id: UUID
    plan_data: Dict[str, Any]
    expected_waste_percentage: float
    status: str = "planned"

class CuttingPlanCreate(CuttingPlanBase):
    pass

class CuttingPlanUpdate(BaseModel):
    status: Optional[str] = None
    plan_data: Optional[Dict[str, Any]] = None
    expected_waste_percentage: Optional[float] = None

class CuttingPlan(CuttingPlanBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

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