from __future__ import annotations
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from uuid import UUID

from .base import CRUDBase
from .. import models, schemas


class CRUDPaper(CRUDBase[models.PaperMaster, schemas.PaperMasterCreate, schemas.PaperMasterUpdate]):
    def get_papers(
        self, db: Session, *, skip: int = 0, limit: int = 100, status: str = "active"
    ) -> List[models.PaperMaster]:
        """Get papers with filtering by status"""
        return (
            db.query(models.PaperMaster)
            .options(joinedload(models.PaperMaster.created_by))
            .filter(models.PaperMaster.status == status)
            .order_by(models.PaperMaster.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
    
    def get_paper(self, db: Session, paper_id: UUID) -> Optional[models.PaperMaster]:
        """Get paper by ID with relationships"""
        return (
            db.query(models.PaperMaster)
            .options(joinedload(models.PaperMaster.created_by))
            .filter(models.PaperMaster.id == paper_id)
            .first()
        )
    
    def get_paper_by_specs(
        self, db: Session, *, gsm: int, bf: float, shade: str
    ) -> Optional[models.PaperMaster]:
        """Get paper by specifications (GSM, BF, Shade)"""
        return (
            db.query(models.PaperMaster)
            .filter(
                and_(
                    models.PaperMaster.gsm == gsm,
                    models.PaperMaster.bf == bf,
                    models.PaperMaster.shade == shade,
                    models.PaperMaster.status == "active"
                )
            )
            .first()
        )
    
    def create_paper(self, db: Session, *, paper: schemas.PaperMasterCreate) -> models.PaperMaster:
        """Create new paper specification"""
        # Check for duplicates
        existing = self.get_paper_by_specs(
            db, gsm=paper.gsm, bf=paper.bf, shade=paper.shade
        )
        if existing:
            raise ValueError(f"Paper with GSM={paper.gsm}, BF={paper.bf}, Shade={paper.shade} already exists")
        
        db_paper = models.PaperMaster(
            name=paper.name,
            gsm=paper.gsm,
            bf=paper.bf,
            shade=paper.shade,
            thickness=paper.thickness,
            type=paper.type,
            created_by_id=paper.created_by_id
        )
        db.add(db_paper)
        db.commit()
        db.refresh(db_paper)
        return db_paper
    
    def update_paper(
        self, db: Session, *, paper_id: UUID, paper_update: schemas.PaperMasterUpdate
    ) -> Optional[models.PaperMaster]:
        """Update paper specification"""
        db_paper = self.get_paper(db, paper_id)
        if db_paper:
            update_data = paper_update.model_dump(exclude_unset=True)
            
            # Check for duplicates if specs are being updated
            if any(field in update_data for field in ["gsm", "bf", "shade"]):
                new_gsm = update_data.get("gsm", db_paper.gsm)
                new_bf = update_data.get("bf", db_paper.bf)
                new_shade = update_data.get("shade", db_paper.shade)
                
                existing = self.get_paper_by_specs(db, gsm=new_gsm, bf=new_bf, shade=new_shade)
                if existing and existing.id != paper_id:
                    raise ValueError(f"Paper with GSM={new_gsm}, BF={new_bf}, Shade={new_shade} already exists")
            
            for field, value in update_data.items():
                setattr(db_paper, field, value)
            db.commit()
            db.refresh(db_paper)
        return db_paper
    
    def delete_paper(self, db: Session, *, paper_id: UUID) -> bool:
        """Soft delete paper (deactivate)"""
        db_paper = self.get_paper(db, paper_id)
        if db_paper:
            db_paper.status = "inactive"
            db.commit()
            return True
        return False
    
    def debug_paper_validation(self, db: Session) -> Dict[str, Any]:
        """Debug paper validation and check for duplicates"""
        papers = db.query(models.PaperMaster).filter(models.PaperMaster.status == "active").all()
        
        duplicates = []
        seen_specs = set()
        
        for paper in papers:
            spec_key = (paper.gsm, float(paper.bf), paper.shade)
            if spec_key in seen_specs:
                duplicates.append({
                    "id": str(paper.id),
                    "name": paper.name,
                    "gsm": paper.gsm,
                    "bf": float(paper.bf),
                    "shade": paper.shade
                })
            else:
                seen_specs.add(spec_key)
        
        return {
            "total_papers": len(papers),
            "unique_specs": len(seen_specs),
            "duplicates_found": len(duplicates),
            "duplicate_papers": duplicates
        }


paper = CRUDPaper(models.PaperMaster)