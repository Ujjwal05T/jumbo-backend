from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base

# User model
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    password = Column(String(100))
    role = Column(String(20), default="user")

# Order model
class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String(100))
    order_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="pending")
    
    # Relationships
    rolls = relationship("CutRoll", back_populates="order")
    whatsapp_message = relationship("WhatsAppMessage", back_populates="order", uselist=False)

# WhatsApp message model
class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    
    id = Column(Integer, primary_key=True, index=True)
    message_text = Column(String(1000))
    received_date = Column(DateTime, default=datetime.utcnow)
    parsed = Column(Boolean, default=False)
    
    # Relationships
    order_id = Column(Integer, ForeignKey("orders.id"))
    order = relationship("Order", back_populates="whatsapp_message")

# Jumbo roll model
class JumboRoll(Base):
    __tablename__ = "jumbo_rolls"
    
    id = Column(Integer, primary_key=True, index=True)
    width = Column(Float)
    length = Column(Float)
    gsm = Column(Float)  # Paper weight in g/m²
    paper_type = Column(String(50))
    date_added = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    cut_rolls = relationship("CutRoll", back_populates="jumbo_roll")

# Cut roll model
class CutRoll(Base):
    __tablename__ = "cut_rolls"
    
    id = Column(Integer, primary_key=True, index=True)
    width = Column(Float)
    length = Column(Float)
    gsm = Column(Float)
    paper_type = Column(String(50))
    qr_code = Column(String(200))
    
    # Relationships
    jumbo_roll_id = Column(Integer, ForeignKey("jumbo_rolls.id"))
    jumbo_roll = relationship("JumboRoll", back_populates="cut_rolls")
    
    order_id = Column(Integer, ForeignKey("orders.id"))
    order = relationship("Order", back_populates="rolls")