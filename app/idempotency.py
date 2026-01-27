"""
Idempotency middleware for preventing duplicate requests
"""
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, Callable
from fastapi import Request, Response, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from . import models

logger = logging.getLogger(__name__)


def generate_request_hash(request_body: dict) -> str:
    """Generate SHA256 hash of request body for additional validation"""
    body_str = json.dumps(request_body, sort_keys=True)
    return hashlib.sha256(body_str.encode()).hexdigest()


def check_idempotency(
    db: Session,
    idempotency_key: str,
    request_path: str,
    request_body: Optional[dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Check if an idempotency key has been seen before.

    Args:
        db: Database session
        idempotency_key: Unique key from client
        request_path: API endpoint path
        request_body: Optional request body for hash validation

    Returns:
        Cached response if key exists and is valid, None otherwise
    """
    try:
        # Look for existing key that hasn't expired
        existing = db.query(models.IdempotencyKey).filter(
            models.IdempotencyKey.key == idempotency_key,
            models.IdempotencyKey.expires_at > datetime.utcnow()
        ).first()

        if existing:
            # Optional: Validate request body hash matches
            if request_body and existing.request_body_hash:
                current_hash = generate_request_hash(request_body)
                if current_hash != existing.request_body_hash:
                    logger.warning(
                        f"Idempotency key {idempotency_key} exists but request body differs. "
                        f"This may indicate different requests using the same key."
                    )
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key already used with different request body"
                    )

            logger.info(f"✅ IDEMPOTENCY: Returning cached response for key: {idempotency_key}")
            return existing.response_body

        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking idempotency key: {e}")
        # On error, continue with request (fail open)
        return None


def store_idempotency_response(
    db: Session,
    idempotency_key: str,
    request_path: str,
    response_body: Any,
    response_status: int = 200,
    request_body: Optional[dict] = None,
    expires_hours: int = 24
) -> None:
    """
    Store the response for an idempotency key.

    Args:
        db: Database session
        idempotency_key: Unique key from client
        request_path: API endpoint path
        response_body: Response to cache
        response_status: HTTP status code
        request_body: Optional request body for hash validation
        expires_hours: Hours until key expires (default 24)
    """
    try:
        # Convert response to JSON-serializable format
        if hasattr(response_body, '__dict__'):
            # Handle SQLAlchemy models
            response_dict = {
                key: str(value) if not isinstance(value, (str, int, float, bool, type(None), list, dict)) else value
                for key, value in response_body.__dict__.items()
                if not key.startswith('_')
            }
        else:
            response_dict = response_body

        # Generate request body hash if provided
        request_hash = generate_request_hash(request_body) if request_body else None

        # Create idempotency record
        idempotency_record = models.IdempotencyKey(
            key=idempotency_key,
            request_path=request_path,
            request_body_hash=request_hash,
            response_body=response_dict,
            response_status=response_status,
            expires_at=datetime.utcnow() + timedelta(hours=expires_hours)
        )

        db.add(idempotency_record)
        db.commit()

        logger.info(f"✅ IDEMPOTENCY: Stored response for key: {idempotency_key}")

    except IntegrityError:
        # Key already exists (race condition), rollback and continue
        db.rollback()
        logger.warning(f"Idempotency key {idempotency_key} already exists (race condition)")
    except Exception as e:
        db.rollback()
        logger.error(f"Error storing idempotency response: {e}")
        # Don't fail the request if we can't store the key


def cleanup_expired_keys(db: Session) -> int:
    """
    Clean up expired idempotency keys.
    Should be called periodically (e.g., via cron job).

    Returns:
        Number of keys deleted
    """
    try:
        deleted_count = db.query(models.IdempotencyKey).filter(
            models.IdempotencyKey.expires_at <= datetime.utcnow()
        ).delete()

        db.commit()
        logger.info(f"Cleaned up {deleted_count} expired idempotency keys")
        return deleted_count

    except Exception as e:
        db.rollback()
        logger.error(f"Error cleaning up expired keys: {e}")
        return 0


def with_idempotency(
    endpoint_func: Callable,
    db: Session,
    idempotency_key: Optional[str],
    request_path: str,
    request_body: Optional[dict] = None
) -> Any:
    """
    Decorator-like function to wrap endpoint with idempotency checking.

    Usage in endpoint:
        if idempotency_key:
            return with_idempotency(
                lambda: crud_operations.create_plan(db=db, plan_data=plan),
                db=db,
                idempotency_key=idempotency_key,
                request_path="/plans",
                request_body=plan.dict()
            )
        else:
            return crud_operations.create_plan(db=db, plan_data=plan)

    Args:
        endpoint_func: Function to execute if no cached response
        db: Database session
        idempotency_key: Unique key from client
        request_path: API endpoint path
        request_body: Optional request body

    Returns:
        Cached response or result of endpoint_func
    """
    # Check for cached response
    cached_response = check_idempotency(db, idempotency_key, request_path, request_body)

    if cached_response:
        return cached_response

    # Execute the endpoint function
    result = endpoint_func()

    # Store the response
    store_idempotency_response(
        db=db,
        idempotency_key=idempotency_key,
        request_path=request_path,
        response_body=result,
        request_body=request_body
    )

    return result
