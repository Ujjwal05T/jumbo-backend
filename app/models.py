from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Table, Text, Boolean, Numeric, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
import uuid
from datetime import datetime
from .database import Base
from enum import Enum as PyEnum
from typing import Optional, List, Dict, Any

class OrderStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class JumboRollStatus(str, PyEnum):
    AVAILABLE = "available"
    CUTTING = "cutting"
    USED = "used"
    PARTIAL = "partial"
    PRODUCED = "produced"

class ProductionOrderStatus(str, PyEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class CuttingPlanStatus(str, PyEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class StatusLog(Base):
    __tablename__ = "status_logs"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    model_type = Column(String(50), nullable=False)  # e.g., 'Order', 'JumboRoll'
    model_id = Column(UNIQUEIDENTIFIER, nullable=False, index=True)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    notes = Column(Text, nullable=True)
    changed_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    changed_by = relationship("User", back_populates="status_logs")
    # Index for faster lookups
    __table_args__ = (
        {'comment': 'Audit log for status changes across all models'},
    )
# User model for authentication
class User(Base):
    __tablename__ = "users"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)  # Storing plain text password
    role = Column(String(20), default="operator", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    # Relationships
    status_logs = relationship("StatusLog", back_populates="changed_by")
    orders = relationship("Order", back_populates="created_by")
    messages = relationship("ParsedMessage", back_populates="created_by")
    jumbo_rolls = relationship("JumboRoll", back_populates="created_by")
    cut_rolls = relationship("CutRoll", back_populates="created_by")
    cutting_plans = relationship("CuttingPlan", back_populates="created_by")
    inventory_logs = relationship("InventoryLog", back_populates="created_by")
    production_orders = relationship("ProductionOrder", back_populates="created_by")

# Parsed message model
class ParsedMessage(Base):
    __tablename__ = "parsed_messages"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    raw_message = Column(Text, nullable=False)  # Store full message text
    received_at = Column(DateTime, default=datetime.utcnow)
    parsed_json = Column(Text)  # Store parsed JSON data
    parsing_status = Column(String(20), nullable=False, default="pending")  # pending, success, failed
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    orders = relationship("Order", back_populates="source_message")
    created_by = relationship("User", back_populates="messages")

# Order model
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    customer_name = Column(String(255), nullable=False)
    width_inches = Column(Integer, nullable=False)
    gsm = Column(Integer, nullable=False)
    bf = Column(Numeric(4, 2), nullable=False)
    shade = Column(String(50), nullable=False)
    quantity_rolls = Column(Integer, nullable=False)
    quantity_fulfilled = Column(Integer, default=0, nullable=False)
    quantity_tons = Column(Numeric(8, 2))
    status = Column(String(50), default=OrderStatus.PENDING, nullable=False)
    source_message_id = Column(UNIQUEIDENTIFIER, ForeignKey("parsed_messages.id"), nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    parent_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"), nullable=True)
    original_order_id = Column(UNIQUEIDENTIFIER, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    source_message = relationship("ParsedMessage", back_populates="orders")
    created_by = relationship("User", back_populates="orders")
    cut_rolls = relationship("CutRoll", back_populates="order")
    inventory_allocations = relationship("InventoryItem", back_populates="allocated_order")
    inventory_logs = relationship("InventoryLog", back_populates="order")
    cutting_plans = relationship("CuttingPlan", back_populates="order")
    production_orders = relationship("ProductionOrder", back_populates="order")
    status_logs = relationship(
        "StatusLog",
        primaryjoin="and_(StatusLog.model_type=='Order', foreign(StatusLog.model_id)==Order.id)",
        overlaps="status_logs"
    )
    backorders = relationship(
        "Order",
        back_populates="parent_order",
        cascade="all, delete-orphan",
        single_parent=True,
        remote_side=[parent_order_id]
    )
    parent_order = relationship(
        "Order",
        remote_side=[id],
        back_populates="backorders",
        post_update=True
    )
    
    @property
    def remaining_quantity(self) -> int:
        return self.quantity_rolls - self.quantity_fulfilled
    
    @property
    def is_fully_fulfilled(self) -> bool:
        return self.quantity_fulfilled >= self.quantity_rolls
    
    @property
    def has_backorders(self) -> bool:
        return len(self.backorders) > 0

# Jumbo roll model
class JumboRoll(Base):
    __tablename__ = "jumbo_rolls"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    width_inches = Column(Integer, default=119, nullable=False)  # Standard jumbo roll width
    weight_kg = Column(Integer, default=4500, nullable=False)  # Standard jumbo roll weight
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(Numeric(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    production_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    status = Column(String(20), nullable=False, default=JumboRollStatus.AVAILABLE)  # available, cutting, used, partial, produced
    production_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("production_orders.id"), nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    cut_rolls = relationship("CutRoll", back_populates="jumbo_roll")
    cutting_plans = relationship("CuttingPlan", back_populates="jumbo_roll")
    created_by = relationship("User", back_populates="jumbo_rolls")
    production_order = relationship("ProductionOrder", back_populates="jumbo_rolls")

# Cut roll model
class CutRoll(Base):
    __tablename__ = "cut_rolls"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("jumbo_rolls.id"), nullable=False)
    width_inches = Column(Integer, nullable=False)  # Cut roll width
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(Numeric(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    weight_kg = Column(Numeric(8, 2))  # Actual weight after cutting and weighing
    qr_code = Column(String(255), unique=True, nullable=False, index=True)  # Unique QR code
    cut_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="cut", nullable=False)  # cut, weighed, allocated, used
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"))
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    jumbo_roll = relationship("JumboRoll", back_populates="cut_rolls")
    order = relationship("Order", back_populates="cut_rolls")
    created_by = relationship("User", back_populates="cut_rolls")
    inventory_item = relationship("InventoryItem", back_populates="roll", uselist=False)
    inventory_logs = relationship("InventoryLog", back_populates="roll")

# Inventory model for tracking cut rolls
class InventoryItem(Base):
    __tablename__ = "inventory"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("cut_rolls.id"), nullable=False, unique=True)
    location = Column(String(100))  # Storage location
    allocated_to_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"))  # If allocated to an order
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    roll = relationship("CutRoll", back_populates="inventory_item")
    allocated_order = relationship("Order", back_populates="inventory_allocations")

# Inventory log model
class InventoryLog(Base):
    __tablename__ = "inventory_logs"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("cut_rolls.id"), nullable=False)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"), nullable=True)
    action = Column(String(50), nullable=False)  # created, allocated, delivered, adjusted, etc.
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    notes = Column(Text, nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    roll = relationship("CutRoll", back_populates="inventory_logs")
    order = relationship("Order", back_populates="inventory_logs")
    created_by = relationship("User", back_populates="inventory_logs")

# Production order for jumbo rolls
class ProductionOrder(Base):
    __tablename__ = "production_orders"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    gsm = Column(Integer, nullable=False)
    bf = Column(Numeric(4, 2), nullable=False)
    shade = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    status = Column(String(20), default=ProductionOrderStatus.PENDING)  # pending, in_production, completed, cancelled
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    jumbo_rolls = relationship("JumboRoll", back_populates="production_order")
    created_by = relationship("User", back_populates="production_orders")
    order = relationship("Order", back_populates="production_orders")

# Enhanced cutting plan model
class CuttingPlan(Base):
    __tablename__ = "cutting_plans"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"), nullable=False)
    jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("jumbo_rolls.id"), nullable=False)
    cut_pattern = Column(Text, nullable=False)  # JSON array of cut widths
    expected_waste_percentage = Column(Numeric(5, 2))
    actual_waste_percentage = Column(Numeric(5, 2), nullable=True)
    status = Column(String(20), default=CuttingPlanStatus.PLANNED, nullable=False)  # planned, in_progress, completed, failed
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    jumbo_roll = relationship("JumboRoll", back_populates="cutting_plans")
    order = relationship("Order", back_populates="cutting_plans")
    created_by = relationship("User", back_populates="cutting_plans")
