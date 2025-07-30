from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional
import logging
import uuid
import json
from uuid import UUID
from datetime import datetime

from .. import crud, schemas, models, database
from ..database import get_db

# ============================================================================
# STATUS VALIDATION UTILITIES
# ============================================================================

def validate_status_transition(current_status: str, new_status: str, entity_type: str) -> bool:
    """
    Validate if a status transition is allowed for a given entity type.
    
    Args:
        current_status: Current status of the entity
        new_status: Desired new status
        entity_type: Type of entity (order, order_item, inventory, pending_order)
    
    Returns:
        bool: True if transition is valid, False otherwise
    """
    valid_transitions = {
        "order": {
            models.OrderStatus.CREATED: [models.OrderStatus.IN_PROCESS, models.OrderStatus.CANCELLED],
            models.OrderStatus.IN_PROCESS: [models.OrderStatus.COMPLETED, models.OrderStatus.CANCELLED],
            models.OrderStatus.COMPLETED: [],  # Terminal state
            models.OrderStatus.CANCELLED: []   # Terminal state
        },
        "order_item": {
            models.OrderItemStatus.CREATED: [models.OrderItemStatus.IN_PROCESS],
            models.OrderItemStatus.IN_PROCESS: [models.OrderItemStatus.IN_WAREHOUSE],
            models.OrderItemStatus.IN_WAREHOUSE: [models.OrderItemStatus.COMPLETED],
            models.OrderItemStatus.COMPLETED: []  # Terminal state
        },
        "inventory": {
            models.InventoryStatus.CUTTING: [models.InventoryStatus.AVAILABLE, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.AVAILABLE: [models.InventoryStatus.ALLOCATED, models.InventoryStatus.USED, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.ALLOCATED: [models.InventoryStatus.USED, models.InventoryStatus.AVAILABLE, models.InventoryStatus.DAMAGED],
            models.InventoryStatus.USED: [],  # Terminal state
            models.InventoryStatus.DAMAGED: []  # Terminal state
        },
        "pending_order": {
            models.PendingOrderStatus.PENDING: [models.PendingOrderStatus.INCLUDED_IN_PLAN, models.PendingOrderStatus.CANCELLED],
            models.PendingOrderStatus.INCLUDED_IN_PLAN: [models.PendingOrderStatus.RESOLVED, models.PendingOrderStatus.CANCELLED],
            models.PendingOrderStatus.RESOLVED: [],  # Terminal state
            models.PendingOrderStatus.CANCELLED: []  # Terminal state
        }
    }
    
    if entity_type not in valid_transitions:
        return False
    
    entity_transitions = valid_transitions[entity_type]
    if current_status not in entity_transitions:
        return False
    
    return new_status in entity_transitions[current_status]

# get_db is imported from database module above

# Create router instance
router = APIRouter()

# Logger setup
logger = logging.getLogger(__name__)