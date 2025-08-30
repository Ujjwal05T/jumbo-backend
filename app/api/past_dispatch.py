from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, and_, or_
from typing import List, Optional
import logging
from datetime import datetime, date
import uuid

from .base import get_db
from .. import models, schemas
from ..services.id_generator import FrontendIDGenerator

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# PAST DISPATCH HISTORY ENDPOINTS
# ============================================================================

@router.get("/past-dispatch/history", tags=["Past Dispatch History"])
def get_past_dispatch_history(
    skip: int = 0,
    limit: int = 50,
    client_name: Optional[str] = None,
    paper_spec: Optional[str] = None,
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Get past dispatch history with filtering and pagination"""
    try:
        # Base query with relationships
        query = db.query(models.PastDispatchRecord).options(
            joinedload(models.PastDispatchRecord.past_dispatch_items)
        )
        
        # Apply filters
        if client_name and client_name.strip() and client_name != "all":
            query = query.filter(models.PastDispatchRecord.client_name.like(f"%{client_name}%"))
        
        if status and status.strip() and status != "all":
            query = query.filter(models.PastDispatchRecord.status == status)
        
        # Date range filters
        if from_date and from_date.strip():
            try:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d")
                query = query.filter(models.PastDispatchRecord.dispatch_date >= from_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid from_date format. Use YYYY-MM-DD")
        
        if to_date and to_date.strip():
            try:
                to_dt = datetime.strptime(to_date, "%Y-%m-%d")
                # Include the entire day
                to_dt = to_dt.replace(hour=23, minute=59, second=59)
                query = query.filter(models.PastDispatchRecord.dispatch_date <= to_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid to_date format. Use YYYY-MM-DD")
        
        # Search filter (search in dispatch number, driver name, vehicle number, client name)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    models.PastDispatchRecord.dispatch_number.like(search_term),
                    models.PastDispatchRecord.driver_name.like(search_term),
                    models.PastDispatchRecord.vehicle_number.like(search_term),
                    models.PastDispatchRecord.client_name.like(search_term)
                )
            )
        
        # Paper spec filter (check in related items)
        if paper_spec and paper_spec.strip() and paper_spec != "all":
            query = query.join(models.PastDispatchItem).filter(
                models.PastDispatchItem.paper_spec.like(f"%{paper_spec}%")
            ).distinct()
        
        # Get total count before pagination
        total_count = query.count()
        
        # Apply pagination and ordering
        dispatches = query.order_by(desc(models.PastDispatchRecord.dispatch_date)).offset(skip).limit(limit).all()
        
        # Format response
        dispatch_list = []
        for dispatch in dispatches:
            dispatch_list.append({
                "id": str(dispatch.id),
                "frontend_id": dispatch.frontend_id,
                "dispatch_number": dispatch.dispatch_number,
                "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
                "client_name": dispatch.client_name,
                "vehicle_number": dispatch.vehicle_number,
                "driver_name": dispatch.driver_name,
                "driver_mobile": dispatch.driver_mobile,
                "payment_type": dispatch.payment_type,
                "status": dispatch.status,
                "total_items": dispatch.total_items,
                "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0.0,
                "created_at": dispatch.created_at.isoformat() if dispatch.created_at else None,
                "delivered_at": dispatch.delivered_at.isoformat() if dispatch.delivered_at else None,
                "items_count": len(dispatch.past_dispatch_items) if dispatch.past_dispatch_items else 0
            })
        
        return {
            "dispatches": dispatch_list,
            "total_count": total_count,
            "current_page": (skip // limit) + 1 if limit > 0 else 1,
            "total_pages": (total_count + limit - 1) // limit if limit > 0 else 1,
            "has_next": skip + limit < total_count,
            "has_previous": skip > 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching past dispatch history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/past-dispatch/{dispatch_id}/details", tags=["Past Dispatch History"])
def get_past_dispatch_details(
    dispatch_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed information for a specific past dispatch record"""
    try:
        dispatch_uuid = uuid.UUID(dispatch_id)
        
        # Query with all relationships
        dispatch = db.query(models.PastDispatchRecord).options(
            joinedload(models.PastDispatchRecord.past_dispatch_items)
        ).filter(models.PastDispatchRecord.id == dispatch_uuid).first()
        
        if not dispatch:
            raise HTTPException(status_code=404, detail="Past dispatch record not found")
        
        # Format dispatch items
        items = []
        for item in dispatch.past_dispatch_items:
            items.append({
                "id": str(item.id),
                "frontend_id": item.frontend_id,
                "width_inches": float(item.width_inches),
                "weight_kg": float(item.weight_kg),
                "rate": float(item.rate) if item.rate else None,
                "paper_spec": item.paper_spec,
            })
        
        return {
            "id": str(dispatch.id),
            "frontend_id": dispatch.frontend_id,
            "dispatch_number": dispatch.dispatch_number,
            "dispatch_date": dispatch.dispatch_date.isoformat() if dispatch.dispatch_date else None,
            "client_name": dispatch.client_name,
            "vehicle_number": dispatch.vehicle_number,
            "driver_name": dispatch.driver_name,
            "driver_mobile": dispatch.driver_mobile,
            "payment_type": dispatch.payment_type,
            "status": dispatch.status,
            "total_items": dispatch.total_items,
            "total_weight_kg": float(dispatch.total_weight_kg) if dispatch.total_weight_kg else 0.0,
            "created_at": dispatch.created_at.isoformat() if dispatch.created_at else None,
            "delivered_at": dispatch.delivered_at.isoformat() if dispatch.delivered_at else None,
            "items": items
        }
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching past dispatch details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/past-dispatch", tags=["Past Dispatch Management"])
def create_past_dispatch_record(
    dispatch_data: dict,
    db: Session = Depends(get_db)
):
    """Create a new past dispatch record with items"""
    try:
        # Extract dispatch record data
        record_data = dispatch_data.get("dispatch_record", {})
        items_data = dispatch_data.get("items", [])
        
        if not record_data:
            raise HTTPException(status_code=400, detail="Dispatch record data is required")
        
        if not items_data:
            raise HTTPException(status_code=400, detail="At least one dispatch item is required")
        
        # Generate frontend ID for dispatch record
        frontend_id = FrontendIDGenerator.generate_frontend_id("past_dispatch_record", db)
        
        # Create dispatch record
        dispatch_record = models.PastDispatchRecord(
            frontend_id=frontend_id,
            vehicle_number=record_data.get("vehicle_number"),
            driver_name=record_data.get("driver_name"),
            driver_mobile=record_data.get("driver_mobile"),
            payment_type=record_data.get("payment_type", "bill"),
            dispatch_date=datetime.fromisoformat(record_data.get("dispatch_date", datetime.now().isoformat())),
            dispatch_number=record_data.get("dispatch_number"),
            client_name=record_data.get("client_name"),
            status=record_data.get("status", "dispatched"),
            total_items=len(items_data),
            total_weight_kg=sum(float(item.get("weight_kg", 0)) for item in items_data)
        )
        
        db.add(dispatch_record)
        db.flush()  # Get the ID
        
        # Create dispatch items
        for item_data in items_data:
            dispatch_item = models.PastDispatchItem(
                frontend_id=item_data.get("frontend_id"),  # User entered manually
                past_dispatch_record_id=dispatch_record.id,
                width_inches=float(item_data.get("width_inches", 0)),
                weight_kg=float(item_data.get("weight_kg", 0)),
                rate=float(item_data.get("rate")) if item_data.get("rate") else None,
                paper_spec=item_data.get("paper_spec")
            )
            db.add(dispatch_item)
        
        db.commit()
        db.refresh(dispatch_record)
        
        return {
            "message": "Past dispatch record created successfully",
            "dispatch_id": str(dispatch_record.id),
            "frontend_id": dispatch_record.frontend_id,
            "total_items": dispatch_record.total_items,
            "total_weight_kg": float(dispatch_record.total_weight_kg)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating past dispatch record: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/past-dispatch/dropdowns", tags=["Past Dispatch Management"])
def get_past_dispatch_dropdowns(db: Session = Depends(get_db)):
    """Get dropdown options for client names and paper specifications"""
    try:
        # Get unique client names from client_master
        clients = db.query(models.ClientMaster.company_name).filter(
            models.ClientMaster.company_name.isnot(None)
        ).distinct().all()
        client_names = [client[0] for client in clients if client[0]]
        
        # Get unique paper specifications from existing past dispatches and current inventory
        past_specs = db.query(models.PastDispatchItem.paper_spec).distinct().all()
        past_paper_specs = [spec[0] for spec in past_specs if spec[0]]
        
        # Get paper specs from current inventory (if available)
        current_specs = []
        try:
            # Try to get from inventory items with paper specs
            inventory_specs = db.query(models.InventoryMaster).join(
                models.PaperMaster
            ).with_entities(
                models.PaperMaster.gsm,
                models.PaperMaster.bf,
                models.PaperMaster.shade
            ).distinct().all()
            
            for spec in inventory_specs:
                spec_str = f"{spec.gsm}gsm, {spec.bf}bf, {spec.shade}"
                if spec_str not in current_specs:
                    current_specs.append(spec_str)
        except:
            pass  # If paper specs not available, continue with past specs only
        
        # Combine and deduplicate paper specs
        all_paper_specs = list(set(past_paper_specs + current_specs))
        all_paper_specs.sort()
        
        return {
            "client_names": sorted(client_names),
            "paper_specs": all_paper_specs,
            "statuses": ["dispatched", "delivered", "returned"],
            "payment_types": ["bill", "cash"]
        }
        
    except Exception as e:
        logger.error(f"Error fetching dropdown options: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/past-dispatch/{dispatch_id}/pdf", tags=["Past Dispatch PDF"])
def generate_past_dispatch_pdf(
    dispatch_id: str,
    db: Session = Depends(get_db)
):
    """Generate PDF for past dispatch record with visual roll representation"""
    try:
        dispatch_uuid = uuid.UUID(dispatch_id)
        
        # Get dispatch with all relationships
        dispatch = db.query(models.PastDispatchRecord).options(
            joinedload(models.PastDispatchRecord.past_dispatch_items)
        ).filter(models.PastDispatchRecord.id == dispatch_uuid).first()
        
        if not dispatch:
            raise HTTPException(status_code=404, detail="Past dispatch record not found")
        
        # Generate PDF content (reuse the same logic as regular dispatch)
        pdf_content = generate_past_dispatch_pdf_content(dispatch)
        
        # Return PDF as response
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=past_dispatch_{dispatch.dispatch_number}_{dispatch.dispatch_date.strftime('%Y%m%d') if dispatch.dispatch_date else 'unknown'}.pdf"
            }
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid dispatch ID format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating past dispatch PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def generate_past_dispatch_pdf_content(dispatch: models.PastDispatchRecord) -> bytes:
    """Generate PDF content for past dispatch record with visual cutting patterns"""
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.graphics.shapes import Drawing, Rect, String
        from reportlab.graphics import renderPDF
        import io
        
        # Create PDF buffer
        buffer = io.BytesIO()
        
        # Create document
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        
        # Build content
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=12,
            alignment=TA_LEFT
        )
        
        # Title
        story.append(Paragraph("PAST DISPATCH RECORD", title_style))
        story.append(Spacer(1, 20))
        
        # Dispatch Information
        dispatch_info = [
            ["Dispatch ID:", dispatch.frontend_id or "N/A"],
            ["Dispatch Number:", dispatch.dispatch_number or "N/A"],
            ["Dispatch Date:", dispatch.dispatch_date.strftime("%d-%m-%Y") if dispatch.dispatch_date else "N/A"],
            ["Status:", dispatch.status or "N/A"],
        ]
        
        dispatch_table = Table(dispatch_info, colWidths=[2*inch, 3*inch])
        dispatch_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(dispatch_table)
        story.append(Spacer(1, 20))
        
        # Client Information (simplified since it's just a name)
        story.append(Paragraph("CLIENT INFORMATION", header_style))
        client_info = [
            ["Client Name:", dispatch.client_name or "N/A"]
        ]
        
        client_table = Table(client_info, colWidths=[2*inch, 3*inch])
        client_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(client_table)
        story.append(Spacer(1, 20))
        
        # Vehicle and Driver Information
        story.append(Paragraph("TRANSPORT DETAILS", header_style))
        transport_info = [
            ["Vehicle Number:", dispatch.vehicle_number or "N/A"],
            ["Driver Name:", dispatch.driver_name or "N/A"],  
            ["Driver Mobile:", dispatch.driver_mobile or "N/A"],
            ["Payment Type:", dispatch.payment_type or "N/A"],
        ]
        
        transport_table = Table(transport_info, colWidths=[2*inch, 3*inch])
        transport_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(transport_table)
        story.append(Spacer(1, 20))
        
        # Dispatch Items
        if dispatch.past_dispatch_items:
            story.append(Paragraph("DISPATCHED ITEMS", header_style))
            
            items_data = [
                ["S.No", "Frontend ID", "Width (inches)", "Weight (kg)", "Rate", "Paper Spec"]
            ]
            
            # Items data
            for i, item in enumerate(dispatch.past_dispatch_items, 1):
                items_data.append([
                    str(i),
                    item.frontend_id or "N/A",
                    f"{float(item.width_inches):.1f}" if item.width_inches else "N/A",
                    f"{float(item.weight_kg):.2f}" if item.weight_kg else "N/A",
                    f"₹{float(item.rate):.2f}" if item.rate else "N/A",
                    item.paper_spec or "N/A"
                ])
            
            items_table = Table(items_data, colWidths=[0.4*inch, 1.0*inch, 0.8*inch, 0.8*inch, 0.8*inch, 2.4*inch])
            items_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(items_table)
            story.append(Spacer(1, 20))
        
        # Summary
        story.append(Paragraph("SUMMARY", header_style))
        summary_info = [
            ["Total Items:", str(dispatch.total_items)],
            ["Total Weight:", f"{float(dispatch.total_weight_kg):.2f} kg" if dispatch.total_weight_kg else "0.00 kg"],
            ["Created At:", dispatch.created_at.strftime("%d-%m-%Y %H:%M") if dispatch.created_at else "N/A"],
        ]
        
        summary_table = Table(summary_info, colWidths=[2*inch, 3*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.grey),
            ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('BACKGROUND', (1, 0), (1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        
        # Build PDF
        doc.build(story)
        
        # Get PDF content
        pdf_content = buffer.getvalue()
        buffer.close()
        
        return pdf_content
        
    except Exception as e:
        logger.error(f"Error generating PDF content: {e}")
        raise Exception(f"Failed to generate PDF: {str(e)}")