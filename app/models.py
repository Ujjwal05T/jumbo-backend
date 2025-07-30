from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Table, Text, Boolean, Numeric, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
import uuid
from datetime import datetime
from .database import Base
from enum import Enum as PyEnum
from typing import Optional, List, Dict, Any

# Status Enums
class OrderStatus(str, PyEnum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PaymentType(str, PyEnum):
    BILL = "bill"
    CASH = "cash"

class OrderItemStatus(str, PyEnum):
    CREATED = "created"
    IN_PROCESS = "in_process"
    IN_WAREHOUSE = "in_warehouse"
    COMPLETED = "completed"

class InventoryStatus(str, PyEnum):
    AVAILABLE = "available"
    ALLOCATED = "allocated"
    CUTTING = "cutting"
    USED = "used"
    DAMAGED = "damaged"

class ProductionOrderStatus(str, PyEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class PlanStatus(str, PyEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class PendingOrderStatus(str, PyEnum):
    PENDING = "pending"
    INCLUDED_IN_PLAN = "included_in_plan"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"

class RollType(str, PyEnum):
    JUMBO = "jumbo"
    CUT = "cut"

# ============================================================================
# MASTER TABLES - Core reference data
# ============================================================================

# Client Master - Stores all client information
class ClientMaster(Base):
    __tablename__ = "client_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    company_name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True)
    gst_number = Column(String(50), nullable=True, index=True)
    address = Column(Text, nullable=True)
    contact_person = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    
    # Relationships
    created_by = relationship("UserMaster", back_populates="clients_created")
    orders = relationship("OrderMaster", back_populates="client")

# User Master - All system users (sales, planners, supervisors)
class UserMaster(Base):
    __tablename__ = "user_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)  # For simple registration
    role = Column(String(50), nullable=False)  # sales, planner, supervisor, admin
    contact = Column(String(255), nullable=True)
    department = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    status = Column(String(20), default="active", nullable=False)
    
    # Relationships
    clients_created = relationship("ClientMaster", back_populates="created_by")
    papers_created = relationship("PaperMaster", back_populates="created_by")
    orders_created = relationship("OrderMaster", back_populates="created_by")
    plans_created = relationship("PlanMaster", back_populates="created_by")
    inventory_created = relationship("InventoryMaster", back_populates="created_by")
    production_orders_created = relationship("ProductionOrderMaster", back_populates="created_by")

# Paper Master - Centralized paper specifications
class PaperMaster(Base):
    __tablename__ = "paper_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False, index=True)  # e.g., "White Bond 90GSM"
    gsm = Column(Integer, nullable=False, index=True)  # Grams per square meter
    bf = Column(Numeric(4, 2), nullable=False, index=True)  # Brightness Factor
    shade = Column(String(50), nullable=False, index=True)  # Paper shade/color
    thickness = Column(Numeric(6, 3), nullable=True)  # Thickness in mm
    type = Column(String(100), nullable=True)  # Bond, Offset, etc.
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    
    # Relationships
    created_by = relationship("UserMaster", back_populates="papers_created")
    order_items = relationship("OrderItem", back_populates="paper")
    inventory_items = relationship("InventoryMaster", back_populates="paper")
    pending_orders = relationship("PendingOrderMaster", back_populates="paper")
    production_orders = relationship("ProductionOrderMaster", back_populates="paper")

# ============================================================================
# TRANSACTION TABLES - Business operations
# ============================================================================

# Order Master - Customer orders (header) linked to Client and Paper masters
class OrderMaster(Base):
    __tablename__ = "order_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    client_id = Column(UNIQUEIDENTIFIER, ForeignKey("client_master.id"), nullable=False, index=True)
    status = Column(String(50), default=OrderStatus.CREATED, nullable=False, index=True)
    priority = Column(String(20), default="normal", nullable=False)  # low, normal, high, urgent
    payment_type = Column(String(20), default=PaymentType.BILL, nullable=False)  # bill, cash
    delivery_date = Column(DateTime, nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_production_at = Column(DateTime, nullable=True)
    moved_to_warehouse_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    
    # Relationships
    client = relationship("ClientMaster", back_populates="orders")
    created_by = relationship("UserMaster", back_populates="orders_created")
    order_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    pending_orders = relationship("PendingOrderMaster", back_populates="original_order")
    plan_orders = relationship("PlanOrderLink", back_populates="order")
    
    @property
    def total_quantity_ordered(self) -> int:
        return sum(item.quantity_rolls for item in self.order_items)
    
    @property
    def total_quantity_fulfilled(self) -> int:
        return sum(item.quantity_fulfilled for item in self.order_items)
    
    @property
    def remaining_quantity(self) -> int:
        return self.total_quantity_ordered - self.total_quantity_fulfilled
    
    @property
    def is_fully_fulfilled(self) -> bool:
        return self.total_quantity_fulfilled >= self.total_quantity_ordered

# Order Item - Individual line items for different widths within an order
class OrderItem(Base):
    __tablename__ = "order_item"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    quantity_rolls = Column(Integer, nullable=False)
    quantity_kg = Column(Numeric(10, 2), nullable=False)  # Weight in kg
    rate = Column(Numeric(10, 2), nullable=False)  # Rate per unit
    amount = Column(Numeric(12, 2), nullable=False)  # Total amount (quantity_kg * rate)
    quantity_fulfilled = Column(Integer, default=0, nullable=False)
    item_status = Column(String(50), default=OrderItemStatus.CREATED, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_production_at = Column(DateTime, nullable=True)
    moved_to_warehouse_at = Column(DateTime, nullable=True)
    dispatched_at = Column(DateTime, nullable=True)
    
    # Relationships
    order = relationship("OrderMaster", back_populates="order_items")
    paper = relationship("PaperMaster", back_populates="order_items")
    
    @property
    def remaining_quantity(self) -> int:
        return self.quantity_rolls - self.quantity_fulfilled
    
    @property
    def is_fully_fulfilled(self) -> bool:
        return self.quantity_fulfilled >= self.quantity_rolls
    
    @staticmethod
    def calculate_quantity_kg(width_inches: int, quantity_rolls: int) -> float:
        """Calculate weight in kg based on width and number of rolls (1 inch roll = 13kg)"""
        return float(width_inches * quantity_rolls * 13)
    
    @staticmethod
    def calculate_quantity_rolls(width_inches: int, quantity_kg: float) -> int:
        """Calculate number of rolls based on width and weight"""
        if width_inches <= 0:
            return 0
        return int(round(quantity_kg / (width_inches * 13)))

# Pending Order Master - Tracks unfulfilled order items for batch processing
class PendingOrderMaster(Base):
    __tablename__ = "pending_order_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    order_item_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_item.id"), nullable=False, index=True)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    quantity_pending = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False)  # no_inventory, no_jumbo, etc.
    status = Column(String(50), default=PendingOrderStatus.PENDING, nullable=False, index=True)
    production_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("production_order_master.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationships
    original_order = relationship("OrderMaster", back_populates="pending_orders")
    order_item = relationship("OrderItem")
    paper = relationship("PaperMaster", back_populates="pending_orders")
    production_order = relationship("ProductionOrderMaster", back_populates="pending_orders")

# Pending Order Item - New model that matches the service expectations
class PendingOrderItem(Base):
    __tablename__ = "pending_order_item"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    original_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    gsm = Column(Integer, nullable=False)
    bf = Column(Numeric(4, 2), nullable=False)
    shade = Column(String(50), nullable=False)
    quantity_pending = Column(Integer, nullable=False)
    reason = Column(String(100), nullable=False, default="no_suitable_jumbo")
    status = Column(String(50), default=PendingOrderStatus.PENDING, nullable=False, index=True)
    production_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("production_order_master.id"), nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationships
    original_order = relationship("OrderMaster", foreign_keys=[original_order_id])
    production_order = relationship("ProductionOrderMaster", back_populates="pending_order_items")
    created_by = relationship("UserMaster")

# Inventory Master - Manages both jumbo and cut rolls
class InventoryMaster(Base):
    __tablename__ = "inventory_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False, index=True)
    weight_kg = Column(Numeric(8, 2), nullable=False)
    roll_type = Column(String(20), nullable=False, index=True)  # jumbo, cut
    location = Column(String(100), nullable=True)
    status = Column(String(50), default=InventoryStatus.AVAILABLE, nullable=False, index=True)
    qr_code = Column(String(255), unique=True, nullable=True, index=True)
    production_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    allocated_to_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    paper = relationship("PaperMaster", back_populates="inventory_items")
    created_by = relationship("UserMaster", back_populates="inventory_created")
    allocated_order = relationship("OrderMaster")
    plan_inventory = relationship("PlanInventoryLink", back_populates="inventory")

# Plan Master - Cutting optimization plans
class PlanMaster(Base):
    __tablename__ = "plan_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=True)  # Optional plan name
    cut_pattern = Column(Text, nullable=False)  # JSON array of cutting pattern
    expected_waste_percentage = Column(Numeric(5, 2), nullable=False)
    actual_waste_percentage = Column(Numeric(5, 2), nullable=True)
    status = Column(String(50), default=PlanStatus.PLANNED, nullable=False, index=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    executed_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    created_by = relationship("UserMaster", back_populates="plans_created")
    plan_orders = relationship("PlanOrderLink", back_populates="plan")
    plan_inventory = relationship("PlanInventoryLink", back_populates="plan")

# Production Order Master - Manufacturing queue for jumbo rolls
class ProductionOrderMaster(Base):
    __tablename__ = "production_order_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)  # Number of jumbo rolls
    priority = Column(String(20), default="normal", nullable=False)  # low, normal, high, urgent
    status = Column(String(50), default=ProductionOrderStatus.PENDING, nullable=False, index=True)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    paper = relationship("PaperMaster", back_populates="production_orders")
    created_by = relationship("UserMaster", back_populates="production_orders_created")
    pending_orders = relationship("PendingOrderMaster", back_populates="production_order")
    pending_order_items = relationship("PendingOrderItem", back_populates="production_order")

# ============================================================================
# LINKING TABLES - Many-to-many relationships
# ============================================================================

# Plan-Order Link - Links plans to multiple order items
class PlanOrderLink(Base):
    __tablename__ = "plan_order_link"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    plan_id = Column(UNIQUEIDENTIFIER, ForeignKey("plan_master.id"), nullable=False, index=True)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    order_item_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_item.id"), nullable=False, index=True)
    quantity_allocated = Column(Integer, nullable=False)  # How many rolls from this order item
    
    # Relationships
    plan = relationship("PlanMaster", back_populates="plan_orders")
    order = relationship("OrderMaster", back_populates="plan_orders")
    order_item = relationship("OrderItem")

# Plan-Inventory Link - Links plans to inventory items used
class PlanInventoryLink(Base):
    __tablename__ = "plan_inventory_link"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    plan_id = Column(UNIQUEIDENTIFIER, ForeignKey("plan_master.id"), nullable=False, index=True)
    inventory_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=False, index=True)
    quantity_used = Column(Numeric(8, 2), nullable=False)  # Weight or length used
    
    # Relationships
    plan = relationship("PlanMaster", back_populates="plan_inventory")
    inventory = relationship("InventoryMaster", back_populates="plan_inventory")

# ============================================================================
# CUT ROLL PRODUCTION TRACKING
# ============================================================================

class CutRollProduction(Base):
    """
    Individual cut roll production tracking with QR code functionality.
    Each record represents one cut roll selected for production from a plan.
    """
    __tablename__ = "cut_roll_production"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    qr_code = Column(String(255), unique=True, nullable=False, index=True)  # Unique QR code
    
    # Cut roll specifications
    width_inches = Column(Numeric(6, 2), nullable=False)
    length_meters = Column(Numeric(8, 2), nullable=True)  # Planned length
    actual_weight_kg = Column(Numeric(8, 2), nullable=True)  # Actual weight when produced
    
    # Paper specifications (denormalized for QR code access)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    gsm = Column(Integer, nullable=False)
    bf = Column(Numeric(4, 2), nullable=False)
    shade = Column(String(100), nullable=False)
    
    # Links to related entities
    plan_id = Column(UNIQUEIDENTIFIER, ForeignKey("plan_master.id"), nullable=False, index=True)
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=True, index=True)  # Original order
    client_id = Column(UNIQUEIDENTIFIER, ForeignKey("client_master.id"), nullable=True, index=True)  # For QR code
    
    # Production tracking
    status = Column(String(50), default="selected", nullable=False, index=True)  # selected, in_production, completed, quality_check, delivered
    individual_roll_number = Column(Integer, nullable=True)  # From cutting algorithm
    trim_left = Column(Numeric(6, 2), nullable=True)  # Waste from cutting pattern
    
    # Timestamps
    selected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    production_started_at = Column(DateTime, nullable=True)
    production_completed_at = Column(DateTime, nullable=True)
    weight_recorded_at = Column(DateTime, nullable=True)
    
    # User tracking
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    weight_recorded_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=True)
    
    # Relationships
    paper = relationship("PaperMaster")
    plan = relationship("PlanMaster")
    order = relationship("OrderMaster")
    client = relationship("ClientMaster")
    created_by = relationship("UserMaster", foreign_keys=[created_by_id])
    weight_recorded_by = relationship("UserMaster", foreign_keys=[weight_recorded_by_id])

# ============================================================================
# DISPATCH TRACKING
# ============================================================================

class DispatchRecord(Base):
    """
    Track bulk dispatch of cut rolls with vehicle and driver details
    """
    __tablename__ = "dispatch_record"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    
    # Dispatch details
    vehicle_number = Column(String(50), nullable=False)
    driver_name = Column(String(255), nullable=False)
    driver_mobile = Column(String(20), nullable=False)
    
    # Payment and reference
    payment_type = Column(String(20), nullable=False, default="bill")  # bill/cash
    dispatch_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    dispatch_number = Column(String(100), nullable=False)  # Internal dispatch number
    reference_number = Column(String(100), nullable=True)  # External reference
    
    # Client and order info
    client_id = Column(UNIQUEIDENTIFIER, ForeignKey("client_master.id"), nullable=False, index=True)
    primary_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=True, index=True)  # Main order if single
    order_date = Column(DateTime, nullable=True)
    
    # Status and tracking
    status = Column(String(50), default="dispatched", nullable=False)  # dispatched, delivered, returned
    total_items = Column(Integer, nullable=False, default=0)
    total_weight_kg = Column(Numeric(10, 2), nullable=False, default=0)
    
    # User tracking
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    
    # Relationships
    client = relationship("ClientMaster")
    primary_order = relationship("OrderMaster")
    created_by = relationship("UserMaster")
    dispatch_items = relationship("DispatchItem", back_populates="dispatch_record")

class DispatchItem(Base):
    """
    Individual cut rolls in a dispatch record
    """
    __tablename__ = "dispatch_item"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    dispatch_record_id = Column(UNIQUEIDENTIFIER, ForeignKey("dispatch_record.id"), nullable=False, index=True)
    inventory_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=False, index=True)
    
    # Cut roll details (denormalized for tracking)
    qr_code = Column(String(255), nullable=False)
    width_inches = Column(Numeric(6, 2), nullable=False)
    weight_kg = Column(Numeric(8, 2), nullable=False)
    paper_spec = Column(String(255), nullable=False)  # "90gsm, 18.0bf, white"
    
    # Status tracking
    status = Column(String(50), default="dispatched", nullable=False)
    dispatched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    dispatch_record = relationship("DispatchRecord", back_populates="dispatch_items")
    inventory = relationship("InventoryMaster")