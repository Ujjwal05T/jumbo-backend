from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import pyotp
import qrcode
import io
import base64
import json
import secrets
import logging
from typing import List

from .base import get_db
from .. import models, schemas, crud_operations

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# TOTP ENDPOINTS (Admin Only)
# ============================================================================

@router.post("/admin/generate-totp/{user_id}", response_model=schemas.TOTPSetupResponse, tags=["TOTP"])
def generate_totp_for_admin(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Generate TOTP secret and QR code for admin user"""
    try:
        # Get the user from database
        from uuid import UUID
        current_user = crud_operations.get_user(db=db, user_id=UUID(user_id))
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Only admins can setup TOTP
        if current_user.role not in ["admin", "co_admin"]:
            raise HTTPException(status_code=403, detail="Only administrators can setup TOTP")

        # Generate a secret key
        secret = pyotp.random_base32()

        # Create TOTP instance
        totp = pyotp.TOTP(secret)

        # Generate QR code
        provisioning_uri = totp.provisioning_uri(
            name=current_user.username,
            issuer_name="JumboRoll System"
        )

        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        # Convert QR code to base64
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        qr_code_base64 = base64.b64encode(buffered.getvalue()).decode()

        # Generate backup codes
        backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]

        # Save to database
        current_user.totp_secret = secret
        current_user.totp_enabled = True
        current_user.totp_backup_codes = json.dumps(backup_codes)
        db.commit()

        logger.info(f"TOTP setup completed for admin user: {current_user.username}")

        return schemas.TOTPSetupResponse(
            secret=secret,
            qr_code=qr_code_base64,
            backup_codes=backup_codes
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating TOTP: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/disable-totp/{user_id}", tags=["TOTP"])
def disable_totp_for_admin(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Disable TOTP for admin user"""
    try:
        # Get the user from database
        from uuid import UUID
        current_user = crud_operations.get_user(db=db, user_id=UUID(user_id))
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Only admins can disable TOTP
        if current_user.role not in ["admin", "co_admin"]:
            raise HTTPException(status_code=403, detail="Only administrators can disable TOTP")

        # Disable TOTP
        current_user.totp_secret = None
        current_user.totp_enabled = False
        current_user.totp_backup_codes = None
        db.commit()

        logger.info(f"TOTP disabled for admin user: {current_user.username}")

        return {"message": "TOTP disabled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error disabling TOTP: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify-admin-otp", response_model=schemas.TOTPVerifyResponse, tags=["TOTP"])
def verify_admin_otp(
    request: schemas.TOTPVerifyRequest,
    db: Session = Depends(get_db)
):
    """Verify OTP code provided by admin for sensitive operations"""
    try:
        # Get the admin user
        admin_user = crud_operations.get_user(db=db, user_id=request.user_id)
        if not admin_user:
            return schemas.TOTPVerifyResponse(valid=False, message="Admin user not found")

        # Check if the user is an admin
        if admin_user.role not in ["admin", "co_admin"]:
            return schemas.TOTPVerifyResponse(valid=False, message="User is not an administrator")

        # Check if TOTP is enabled
        if not admin_user.totp_enabled or not admin_user.totp_secret:
            return schemas.TOTPVerifyResponse(valid=False, message="TOTP not enabled for this admin")

        # Verify the OTP code
        totp = pyotp.TOTP(admin_user.totp_secret)
        is_valid = totp.verify(request.otp_code, valid_window=1)  # Allow 1 window for clock drift

        if not is_valid:
            # Check backup codes
            if admin_user.totp_backup_codes:
                backup_codes = json.loads(admin_user.totp_backup_codes)
                if request.otp_code.upper() in backup_codes:
                    # Remove used backup code
                    backup_codes.remove(request.otp_code.upper())
                    admin_user.totp_backup_codes = json.dumps(backup_codes)
                    db.commit()
                    is_valid = True
                    logger.info(f"Backup code used for admin: {admin_user.username}")

        if is_valid:
            logger.info(f"Valid OTP provided for admin: {admin_user.username}")
            return schemas.TOTPVerifyResponse(valid=True, message="OTP verified successfully")
        else:
            logger.warning(f"Invalid OTP attempt for admin: {admin_user.username}")
            return schemas.TOTPVerifyResponse(valid=False, message="Invalid OTP code")

    except Exception as e:
        logger.error(f"Error verifying OTP: {e}")
        return schemas.TOTPVerifyResponse(valid=False, message="Error verifying OTP")

@router.get("/admin/totp-status/{user_id}", tags=["TOTP"])
def get_admin_totp_status(
    user_id: str,
    db: Session = Depends(get_db)
):
    """Get TOTP status for admin user"""
    try:
        # Get the user from database
        from uuid import UUID
        current_user = crud_operations.get_user(db=db, user_id=UUID(user_id))
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Only admins can check TOTP status
        if current_user.role not in ["admin", "co_admin"]:
            raise HTTPException(status_code=403, detail="Only administrators can check TOTP status")

        return {
            "totp_enabled": current_user.totp_enabled,
            "has_backup_codes": bool(current_user.totp_backup_codes)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting TOTP status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/list", tags=["TOTP"])
def get_admin_list(
    db: Session = Depends(get_db)
):
    """Get list of admin users for OTP verification selection"""
    try:
        # Get all admin users with TOTP enabled
        admins = db.query(models.UserMaster).filter(
            models.UserMaster.role.in_(["admin", "co_admin"]),
            models.UserMaster.totp_enabled == True,
            models.UserMaster.status == "active"
        ).all()

        return [
            {
                "id": admin.id,
                "name": admin.name,
                "username": admin.username,
                "totp_enabled": admin.totp_enabled
            }
            for admin in admins
        ]

    except Exception as e:
        logger.error(f"Error getting admin list: {e}")
        raise HTTPException(status_code=500, detail=str(e))