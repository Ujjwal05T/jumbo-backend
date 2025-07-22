from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

# User schemas
class UserBase(BaseModel):
    username: str
    role: str = "user"

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: int
    
    class Config:
        orm_mode = True

# Order schemas
class OrderBase(BaseModel):
    customer_name: str
    status: str = "pending"

class OrderCreate(OrderBase):
    pass

class Order(OrderBase):
    id: int
    order_date: datetime
    
    class Config:
        orm_mode = True

# WhatsApp message schemas
class WhatsAppMessageBase(BaseModel):
    message_text: str
    parsed: bool = False

class WhatsAppMessageCreate(WhatsAppMessageBase):
    pass

class WhatsAppMessage(WhatsAppMessageBase):
    id: int
    received_date: datetime
    order_id: Optional[int] = None
    
    class Config:
        orm_mode = True

# Jumbo roll schemas
class JumboRollBase(BaseModel):
    width: float
    length: float
    gsm: float
    paper_type: str

class JumboRollCreate(JumboRollBase):
    pass

class JumboRoll(JumboRollBase):
    id: int
    date_added: datetime
    
    class Config:
        orm_mode = True

# Cut roll schemas
class CutRollBase(BaseModel):
    width: float
    length: float
    gsm: float
    paper_type: str
    qr_code: Optional[str] = None

class CutRollCreate(CutRollBase):
    jumbo_roll_id: int
    order_id: int

class CutRoll(CutRollBase):
    id: int
    jumbo_roll_id: int
    order_id: int
    
    class Config:
        orm_mode = True