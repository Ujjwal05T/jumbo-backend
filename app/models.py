from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, DECIMAL, Index
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from .database import Base

# User model for authentication
class User(Base):
    __tablename__ = "users"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)  # Will store hashed passwords
    role = Column(String(20), default="operator", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user")
    created_orders = relationship("Order", back_populates="created_by_user")
    created_messages = relationship("WhatsAppMessage", back_populates="created_by_user")
    created_jumbo_rolls = relationship("JumboRoll", back_populates="created_by_user")
    created_cut_rolls = relationship("CutRoll", back_populates="created_by_user")
    created_cutting_plans = relationship("CuttingPlan", back_populates="created_by_user")

# User session model for authentication
class UserSession(Base):
    __tablename__ = "user_sessions"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Relationships
    user = relationship("User", back_populates="sessions")

# WhatsApp message model
class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    raw_message = Column(Text, nullable=False)  # Store full WhatsApp message
    sender = Column(String(100))
    received_at = Column(DateTime, default=datetime.utcnow)
    parsed_json = Column(Text)  # Store parsed JSON data
    parsing_confidence = Column(DECIMAL(5, 2))  # Confidence score from GPT parsing
    parsing_status = Column(String(20), nullable=False, default="pending")  # pending, success, failed
    created_by = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    created_by_user = relationship("User", back_populates="created_messages")
    orders = relationship("Order", back_populates="source_message")

# Order model
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    customer_name = Column(String(255), nullable=False)
    width_inches = Column(Integer, nullable=False)  # Roll width in inches
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(DECIMAL(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    quantity_rolls = Column(Integer, nullable=False)  # Number of rolls
    quantity_tons = Column(DECIMAL(8, 2))  # Weight in tons (optional)
    status = Column(String(20), default="pending", nullable=False)  # pending, processing, completed, cancelled
    source_message_id = Column(UNIQUEIDENTIFIER, ForeignKey("whatsapp_messages.id"))
    created_by = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    source_message = relationship("WhatsAppMessage", back_populates="orders")
    created_by_user = relationship("User", back_populates="created_orders")
    cut_rolls = relationship("CutRoll", back_populates="order")
    inventory_allocations = relationship("InventoryItem", back_populates="allocated_order")

# Jumbo roll model
class JumboRoll(Base):
    __tablename__ = "jumbo_rolls"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    width_inches = Column(Integer, default=119, nullable=False)  # Standard jumbo roll width
    weight_kg = Column(Integer, default=4500, nullable=False)  # Standard jumbo roll weight
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(DECIMAL(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    production_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="available")  # available, cutting, used
    created_by = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    created_by_user = relationship("User", back_populates="created_jumbo_rolls")
    cut_rolls = relationship("CutRoll", back_populates="jumbo_roll")
    cutting_plans = relationship("CuttingPlan", back_populates="jumbo_roll")

# Cut roll model
class CutRoll(Base):
    __tablename__ = "cut_rolls"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("jumbo_rolls.id"), nullable=False)
    width_inches = Column(Integer, nullable=False)  # Cut roll width
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(DECIMAL(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    weight_kg = Column(DECIMAL(8, 2))  # Actual weight after cutting and weighing
    qr_code = Column(String(255), unique=True, nullable=False, index=True)  # Unique QR code
    cut_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="cut", nullable=False)  # cut, weighed, allocated, used
    order_id = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"))
    created_by = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    jumbo_roll = relationship("JumboRoll", back_populates="cut_rolls")
    order = relationship("Order", back_populates="cut_rolls")
    created_by_user = relationship("User", back_populates="created_cut_rolls")
    inventory_item = relationship("InventoryItem", back_populates="roll", uselist=False)

# Inventory model for tracking cut rolls
class InventoryItem(Base):
    __tablename__ = "inventory"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("cut_rolls.id"), nullable=False, unique=True)
    location = Column(String(100))  # Storage location
    allocated_to_order = Column(UNIQUEIDENTIFIER, ForeignKey("orders.id"))  # If allocated to an order
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    roll = relationship("CutRoll", back_populates="inventory_item")
    allocated_order = relationship("Order", back_populates="inventory_allocations")

# Cutting plan model
class CuttingPlan(Base):
    __tablename__ = "cutting_plans"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("jumbo_rolls.id"), nullable=False)
    plan_data = Column(Text, nullable=False)  # JSON data containing cutting plan details
    expected_waste_percentage = Column(DECIMAL(5, 2))  # Expected waste percentage
    status = Column(String(20), default="planned", nullable=False)  # planned, approved, executing, completed
    created_by = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    jumbo_roll = relationship("JumboRoll", back_populates="cutting_plans")
    created_by_user = relationship("User", back_populates="created_cutting_plans")

# Create indexes for performance optimization
Index('idx_orders_status', Order.status)
Index('idx_orders_customer', Order.customer_name)
Index('idx_orders_specs', Order.width_inches, Order.gsm, Order.bf, Order.shade)
Index('idx_cut_rolls_specs', CutRoll.width_inches, CutRoll.gsm, CutRoll.bf, CutRoll.shade)
Index('idx_cut_rolls_status', CutRoll.status)
Index('idx_jumbo_rolls_specs', JumboRoll.gsm, JumboRoll.bf, JumboRoll.shade)
Index('idx_jumbo_rolls_status', JumboRoll.status)
Index('idx_inventory_allocation', InventoryItem.allocated_to_order)
Index('idx_whatsapp_parsing_status', WhatsAppMessage.parsing_status)
Index('idx_user_sessions_token', UserSession.session_token)
Index('idx_user_sessions_active', UserSession.is_active, UserSession.expires_at)