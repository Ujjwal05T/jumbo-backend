from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Table, Text, Boolean, Numeric, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
import uuid
from datetime import datetime
from .database import Base
from enum import Enum as PyEnum

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
    orders = relationship("Order", back_populates="created_by")
    messages = relationship("ParsedMessage", back_populates="created_by")
    jumbo_rolls = relationship("JumboRoll", back_populates="created_by")
    cut_rolls = relationship("CutRoll", back_populates="created_by")
    cutting_plans = relationship("CuttingPlan", back_populates="created_by")

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
    width_inches = Column(Integer, nullable=False)  # Roll width in inches
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(Numeric(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    quantity_rolls = Column(Integer, nullable=False)  # Number of rolls
    quantity_tons = Column(Numeric(8, 2))  # Weight in tons (optional)
    status = Column(String(20), default="pending", nullable=False)  # pending, processing, completed, cancelled
    source_message_id = Column(UNIQUEIDENTIFIER, ForeignKey("parsed_messages.id"))
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    source_message = relationship("ParsedMessage", back_populates="orders")
    created_by = relationship("User", back_populates="orders")
    cut_rolls = relationship("CutRoll", back_populates="order")
    inventory_allocations = relationship("InventoryItem", back_populates="allocated_order")

# Jumbo roll model
class JumboRoll(Base):
    __tablename__ = "jumbo_rolls"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    width_inches = Column(Integer, default=119, nullable=False)  # Standard jumbo roll width
    weight_kg = Column(Integer, default=4500, nullable=False)  # Standard jumbo roll weight
    gsm = Column(Integer, nullable=False)  # Grams per square meter
    bf = Column(Numeric(4, 2), nullable=False)  # Brightness Factor
    shade = Column(String(50), nullable=False)  # Paper shade/color
    production_date = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False, default="available")  # available, cutting, used
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    cut_rolls = relationship("CutRoll", back_populates="jumbo_roll")
    cutting_plans = relationship("CuttingPlan", back_populates="jumbo_roll")
    created_by = relationship("User", back_populates="jumbo_rolls")

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

# Cutting plan model
class CuttingPlan(Base):
    __tablename__ = "cutting_plans"
    
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4, index=True)
    jumbo_roll_id = Column(UNIQUEIDENTIFIER, ForeignKey("jumbo_rolls.id"), nullable=False)
    plan_data = Column(Text, nullable=False)  # JSON data containing cutting plan details
    expected_waste_percentage = Column(Numeric(5, 2))  # Expected waste percentage
    status = Column(String(20), default="planned", nullable=False)  # planned, approved, executing, completed
    created_by_id = Column(UNIQUEIDENTIFIER, ForeignKey("users.id"))
    
    # Relationships
    jumbo_roll = relationship("JumboRoll", back_populates="cutting_plans")
    created_by = relationship("User", back_populates="cutting_plans")
