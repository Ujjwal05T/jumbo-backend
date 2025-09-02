from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Table, Text, Boolean, Numeric, Enum, event
from sqlalchemy.orm import relationship, Session
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

class WastageStatus(str, PyEnum):
    AVAILABLE = "available"
    USED = "used"
    DAMAGED = "damaged"

class RollType(str, PyEnum):
    JUMBO = "jumbo"
    ROLL_118 = "118"
    CUT = "cut"

class InventoryItemStatus(str, PyEnum):
    AVAILABLE = "available"
    IN_DISPATCH = "in_dispatch" 
    DISPATCHED = "dispatched"
    DAMAGED = "damaged"

# ============================================================================
# MASTER TABLES - Core reference data
# ============================================================================

# Client Master - Stores all client information
class ClientMaster(Base):
    __tablename__ = "client_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # CL-001, CL-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # USR-001, USR-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # PAP-001, PAP-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # ORD-2025-001, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # ORI-001, ORI-002, etc.
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    quantity_rolls = Column(Integer, nullable=False)
    quantity_kg = Column(Numeric(10, 2), nullable=False)  # Weight in kg
    rate = Column(Numeric(10, 2), nullable=False)  # Rate per unit
    amount = Column(Numeric(12, 2), nullable=False)  # Total amount (quantity_kg * rate)
    quantity_fulfilled = Column(Integer, default=0, nullable=False)
    quantity_in_pending = Column(Integer, default=0, nullable=False)  # Track quantities in pending orders
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
    def remaining_to_plan(self) -> int:
        """Calculate how much quantity is still available for planning (not fulfilled and not in pending)"""
        return max(0, self.quantity_rolls - self.quantity_fulfilled - self.quantity_in_pending)
    
    @property
    def is_fully_fulfilled(self) -> bool:
        return self.quantity_fulfilled >= self.quantity_rolls
    
    @staticmethod
    def calculate_quantity_kg(width_inches: float, quantity_rolls: int) -> float:
        """Calculate weight in kg based on width and number of rolls (1 inch roll = 13kg)"""
        return float(width_inches * quantity_rolls * 13)
    
    @staticmethod
    def calculate_quantity_rolls(width_inches: float, quantity_kg: float) -> int:
        """Calculate number of rolls based on width and weight"""
        if width_inches <= 0:
            return 0
        return int(round(quantity_kg / (width_inches * 13)))

# Pending Order Master - Tracks unfulfilled order items for batch processing
class PendingOrderMaster(Base):
    __tablename__ = "pending_order_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # POM-001, POM-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # POI-001, POI-002, etc.
    original_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    gsm = Column(Integer, nullable=False)
    bf = Column(Numeric(4, 2), nullable=False)
    shade = Column(String(50), nullable=False)
    quantity_pending = Column(Integer, nullable=False)
    quantity_fulfilled = Column(Integer, default=0, nullable=False)
    reason = Column(String(100), nullable=False, default="no_suitable_jumbo")
    _status = Column("status", String(50), default=PendingOrderStatus.PENDING, nullable=False, index=True)
    production_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("production_order_master.id"), nullable=True)
    
    # Plan generation tracking fields (kept for database compatibility)
    generated_cut_rolls_count = Column(Integer, default=0, nullable=False)  # How many cut rolls were generated from this pending order?
    plan_generation_date = Column(DateTime, nullable=True)  # When was this included in plan generation?
    included_in_plan_generation = Column(Boolean, default=False, nullable=False)  # Whether this was included in plan generation
    
    @property
    def status(self):
        """Get the status of the pending order item."""
        return self._status
    
    @status.setter
    def status(self, value):
        """
        Set status with validation to prevent improper transitions to included_in_plan.
        This helps catch accidental direct status assignments that bypass proper workflow.
        """
        import logging
        import inspect
        
        # Allow initial setting during object creation
        if not hasattr(self, '_status') or self._status is None:
            self._status = value
            return
            
        # Get caller information for debugging
        frame = inspect.currentframe()
        caller_info = "unknown"
        if frame and frame.f_back:
            caller_info = f"{frame.f_back.f_code.co_filename}:{frame.f_back.f_lineno}"
        
        logger = logging.getLogger(__name__)
        
        # Warn if someone tries to set included_in_plan directly
        if value == "included_in_plan" and self._status != "included_in_plan":
            logger.warning(f"Direct status assignment to 'included_in_plan' detected for pending order {getattr(self, 'frontend_id', 'unknown')} from {caller_info}. Consider using mark_as_included_in_plan() method instead.")
        
        # Log all status changes for audit trail
        if self._status != value:
            logger.info(f"Pending order {getattr(self, 'frontend_id', 'unknown')} status changed from '{self._status}' to '{value}' (called from {caller_info})")
        
        self._status = value
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    
    # Relationships
    original_order = relationship("OrderMaster", foreign_keys=[original_order_id])
    production_order = relationship("ProductionOrderMaster", back_populates="pending_order_items")
    created_by = relationship("UserMaster")
    
    # Status validation methods
    def can_transition_to_included_in_plan(self) -> bool:
        """
        Check if this pending order can be marked as included_in_plan.
        Only allow this transition during production start, not during plan generation.
        """
        return self.status == "pending"
    
    def mark_as_included_in_plan(self, session: Session, resolved_by_production: bool = False) -> bool:
        """
        Safely mark pending order as included_in_plan with validation.
        
        Args:
            session: Database session for logging
            resolved_by_production: True if this is being called during production start
        
        Returns:
            bool: True if status was updated, False if transition not allowed
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔧 DEBUG: mark_as_included_in_plan called for {self.frontend_id}")
        logger.info(f"🔧 DEBUG: resolved_by_production = {resolved_by_production}")
        logger.info(f"🔧 DEBUG: current status = {self.status}")
        logger.info(f"🔧 DEBUG: can_transition = {self.can_transition_to_included_in_plan()}")
        
        if not resolved_by_production:
            # Log warning and prevent status change during plan generation
            logger.warning(f"PREVENTED: Attempted to mark pending order {self.frontend_id} as included_in_plan during plan generation. This should only happen during production start.")
            return False
            
        if self.can_transition_to_included_in_plan():
            logger.info(f"🔧 DEBUG: Setting status to included_in_plan for {self.frontend_id}")
            self.status = "included_in_plan"
            self.resolved_at = datetime.utcnow()
            logger.info(f"🔧 DEBUG: Status after update = {self.status}")
            return True
        else:
            logger.warning(f"🔧 DEBUG: Cannot transition to included_in_plan for {self.frontend_id} - current status is {self.status}")
            return False

# Inventory Master - Manages both jumbo and cut rolls
class InventoryMaster(Base):
    __tablename__ = "inventory_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # INV-001, INV-002, etc.
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    width_inches = Column(Numeric(6, 2), nullable=False, index=True)
    weight_kg = Column(Numeric(8, 2), nullable=False)
    roll_type = Column(String(20), nullable=False, index=True)  # jumbo, cut
    location = Column(String(100), nullable=True)
    status = Column(String(50), default=InventoryStatus.AVAILABLE, nullable=False, index=True)
    qr_code = Column(String(255), unique=True, nullable=True, index=True)  # Kept for compatibility
    barcode_id = Column(String(50), unique=True, nullable=True, index=True)  # Human-readable barcode ID
    production_date = Column(DateTime, default=datetime.utcnow, nullable=False)
    allocated_to_order_id = Column(UNIQUEIDENTIFIER, ForeignKey("order_master.id"), nullable=True)
    
    # Source tracking fields for pending order resolution
    source_type = Column(String(50), nullable=True, index=True)  # 'regular_order' or 'pending_order'
    source_pending_id = Column(UNIQUEIDENTIFIER, ForeignKey("pending_order_item.id"), nullable=True, index=True)
    
    # Jumbo roll hierarchy tracking fields
    parent_jumbo_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=True, index=True)
    parent_118_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=True, index=True)
    roll_sequence = Column(Integer, nullable=True)  # Position within jumbo (1, 2, 3)
    individual_roll_number = Column(Integer, nullable=True)  # From optimization algorithm
    
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    paper = relationship("PaperMaster", back_populates="inventory_items")
    created_by = relationship("UserMaster", back_populates="inventory_created")
    allocated_order = relationship("OrderMaster")
    source_pending_order = relationship("PendingOrderItem", foreign_keys=[source_pending_id])
    plan_inventory = relationship("PlanInventoryLink", back_populates="inventory")
    
    # Jumbo roll hierarchy relationships
    parent_jumbo = relationship("InventoryMaster", foreign_keys=[parent_jumbo_id], remote_side=[id])
    parent_118_roll = relationship("InventoryMaster", foreign_keys=[parent_118_roll_id], remote_side=[id])
    child_118_rolls = relationship("InventoryMaster", foreign_keys=[parent_jumbo_id], back_populates="parent_jumbo")
    child_cut_rolls = relationship("InventoryMaster", foreign_keys=[parent_118_roll_id], back_populates="parent_118_roll")

# Plan Master - Cutting optimization plans
class PlanMaster(Base):
    __tablename__ = "plan_master"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # PLN-2025-001, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # PRO-001, PRO-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # POL-001, POL-002, etc.
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # PIL-001, PIL-002, etc.
    plan_id = Column(UNIQUEIDENTIFIER, ForeignKey("plan_master.id"), nullable=False, index=True)
    inventory_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=False, index=True)
    quantity_used = Column(Numeric(8, 2), nullable=False)  # Weight or length used
    
    # Relationships
    plan = relationship("PlanMaster", back_populates="plan_inventory")
    inventory = relationship("InventoryMaster", back_populates="plan_inventory")


# ============================================================================
# DISPATCH TRACKING
# ============================================================================

class DispatchRecord(Base):
    """
    Track bulk dispatch of cut rolls with vehicle and driver details
    """
    __tablename__ = "dispatch_record"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # DSP-2025-001, etc.
    
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
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # DSI-001, DSI-002, etc.
    dispatch_record_id = Column(UNIQUEIDENTIFIER, ForeignKey("dispatch_record.id"), nullable=False, index=True)
    inventory_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=False, index=True)
    
    # Cut roll details (denormalized for tracking)
    qr_code = Column(String(255), nullable=False)
    barcode_id = Column(String(50), nullable=True)
    width_inches = Column(Numeric(6, 2), nullable=False)
    weight_kg = Column(Numeric(8, 2), nullable=False)
    paper_spec = Column(String(255), nullable=False)  # "90gsm, 18.0bf, white"
    
    # Status tracking
    status = Column(String(50), default="dispatched", nullable=False)
    dispatched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    dispatch_record = relationship("DispatchRecord", back_populates="dispatch_items")
    inventory = relationship("InventoryMaster")


class PastDispatchRecord(Base):
    """
    Historical dispatch records for viewing purposes only.
    Denormalized data - no foreign key relationships to current tables.
    """
    __tablename__ = "past_dispatch_record"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # PDR-25-08-0001
    
    # Dispatch details
    vehicle_number = Column(String(50), nullable=False)
    driver_name = Column(String(255), nullable=False)
    driver_mobile = Column(String(20), nullable=False)
    
    # Payment and reference
    payment_type = Column(String(20), nullable=False, default="bill")  # bill/cash
    dispatch_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    dispatch_number = Column(String(100), nullable=False)
    
    # Client info (denormalized - no FK)
    client_name = Column(String(255), nullable=False)  # Stored as text, dropdown in frontend
    
    # Status and tracking
    status = Column(String(50), default="dispatched", nullable=False)  # dispatched, delivered, returned
    total_items = Column(Integer, nullable=False, default=0)
    total_weight_kg = Column(Numeric(10, 2), nullable=False, default=0)
    
    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    
    # Relationships
    past_dispatch_items = relationship("PastDispatchItem", back_populates="past_dispatch_record", cascade="all, delete-orphan")


class PastDispatchItem(Base):
    """
    Historical dispatch items for viewing purposes only.
    Denormalized data - no foreign key relationships to current inventory.
    """
    __tablename__ = "past_dispatch_item"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), nullable=True, index=True)  # MANUALLY ENTERED BY USER
    past_dispatch_record_id = Column(UNIQUEIDENTIFIER, ForeignKey("past_dispatch_record.id"), nullable=False, index=True)
    
    # Physical properties
    width_inches = Column(Numeric(6, 2), nullable=False)
    weight_kg = Column(Numeric(8, 2), nullable=False)
    rate = Column(Numeric(10, 2), nullable=True)  # Rate per unit
    
    # Paper specification (denormalized - no FK)
    paper_spec = Column(String(255), nullable=False)  # e.g., "90gsm, 18.0bf, white"
    
    # Relationships
    past_dispatch_record = relationship("PastDispatchRecord", back_populates="past_dispatch_items")


class WastageInventory(Base):
    """
    Wastage inventory for tracking waste material (9-21 inches)
    Generated during production when trim/waste is between 9-21 inches
    """
    __tablename__ = "wastage_inventory"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    frontend_id = Column(String(50), unique=True, nullable=True, index=True)  # WS-00001, WS-00002, etc.
    barcode_id = Column(String(50), unique=True, nullable=True, index=True)   # WSB-00001, WSB-00002, etc.
    
    # Wastage details
    width_inches = Column(Numeric(6, 2), nullable=False)  # Width of the waste material
    paper_id = Column(UNIQUEIDENTIFIER, ForeignKey("paper_master.id"), nullable=False, index=True)
    weight_kg = Column(Numeric(8, 2), default=0.0)  # Weight will be set via QR scan
    
    # Source information
    source_plan_id = Column(UNIQUEIDENTIFIER, ForeignKey("plan_master.id"), nullable=True, index=True)
    source_jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("inventory_master.id"), nullable=True, index=True)
    individual_roll_number = Column(Integer, nullable=True)  # Which 118" roll this waste came from
    
    # Status and tracking
    status = Column(String(50), default=WastageStatus.AVAILABLE.value, nullable=False)
    location = Column(String(255), default="WASTE_STORAGE", nullable=True)
    
    # Audit fields
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("user_master.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Notes for special handling
    notes = Column(Text, nullable=True)
    
    # Relationships
    paper = relationship("PaperMaster")
    source_plan = relationship("PlanMaster")
    source_jumbo_roll = relationship("InventoryMaster", foreign_keys=[source_jumbo_roll_id])
    created_by = relationship("UserMaster")


# ============================================================================
# INVENTORY ITEMS - Individual reel tracking with barcode functionality
# ============================================================================

class InventoryItem(Base):
    """
    Individual reel tracking for inventory management.
    Based on imported stock data with basic fields for display.
    """
    __tablename__ = "inventory_items"
    
    stock_id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    sno_from_file = Column(Integer, nullable=True)
    reel_no = Column(String(50), nullable=True, index=True)
    gsm = Column(Integer, nullable=True, index=True)
    bf = Column(Integer, nullable=True, index=True)
    size = Column(String(50), nullable=True, index=True)  # Original size value as text
    weight_kg = Column(Float, nullable=True)
    grade = Column(String(10), nullable=True)
    stock_date = Column(DateTime, nullable=True)
    record_imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================================
# FRONTEND ID GENERATION - Auto-generate human-readable IDs on record creation
# ============================================================================

def generate_frontend_id_on_insert(mapper, connection, target):
    """
    SQLAlchemy event handler to generate frontend_id before insert.
    This function is called automatically when new records are inserted.
    """
    from app.services.id_generator import FrontendIDGenerator
    
    if target.frontend_id is None:  # Only generate if not already provided
        table_name = target.__tablename__
        
        # Create a temporary session for the ID generation
        from sqlalchemy.orm import sessionmaker
        Session = sessionmaker(bind=connection)
        session = Session()
        
        try:
            target.frontend_id = FrontendIDGenerator.generate_frontend_id(table_name, session)
        finally:
            session.close()


# Register event listeners for all models that have frontend_id
models_with_frontend_id = [
    ClientMaster,
    UserMaster, 
    PaperMaster,
    OrderMaster,
    OrderItem,
    PendingOrderMaster,
    PendingOrderItem,  # Re-enabled with thread-safe ID generation
    InventoryMaster,
    PlanMaster,
    ProductionOrderMaster,
    PlanOrderLink,
    PlanInventoryLink,
    DispatchRecord,
    DispatchItem,
    WastageInventory
]

for model in models_with_frontend_id:
    event.listen(model, 'before_insert', generate_frontend_id_on_insert)