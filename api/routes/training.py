"""
Training API Routes

Endpoints for managing extraction training:
- Submit corrections from review
- Get training statistics
- Manage extraction rules
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from api.training_db import get_session, init_training_db
from models.training import (
    ExtractionRule,
    FieldCorrectionCreate,
)
from services.training_service import TrainingService


def init_training_schema():
    """Initialize training tables in the database."""
    init_training_db()


router = APIRouter(prefix="/training", tags=["Training"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class CorrectionItem(BaseModel):
    field_key: str
    predicted_value: Optional[str] = None
    corrected_value: Optional[str] = None
    was_correct: bool = False


class SubmitCorrectionsRequest(BaseModel):
    extraction_run_id: int
    corrections: list[CorrectionItem]
    mark_as_validated: bool = True
    stay_in_training: bool = True  # Don't redirect to runs


class SubmitCorrectionsResponse(BaseModel):
    success: bool
    saved_count: int
    error_count: int
    message: str
    training_stats: dict


class TrainingStatsResponse(BaseModel):
    by_auction_type: dict


class RuleResponse(BaseModel):
    id: int
    field_key: str
    rule_type: str
    label_patterns: list[str]
    exclude_patterns: list[str]
    confidence: float
    validation_count: int
    is_active: bool


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.post("/submit-corrections", response_model=SubmitCorrectionsResponse)
def submit_corrections(request: SubmitCorrectionsRequest, session: Session = Depends(get_session)):
    """
    Submit field corrections from review page.

    This endpoint:
    1. Saves all corrections to the database
    2. Creates a training example from the corrections
    3. Triggers learning to update extraction rules
    4. Returns updated training stats
    """
    service = TrainingService(session)

    # Convert request corrections to model format
    corrections = [
        FieldCorrectionCreate(
            field_key=c.field_key,
            predicted_value=c.predicted_value,
            corrected_value=c.corrected_value,
            was_correct=c.was_correct,
        )
        for c in request.corrections
    ]

    try:
        saved_count, error_count = service.save_corrections(
            run_id=request.extraction_run_id,
            corrections=corrections,
            mark_validated=request.mark_as_validated,
        )

        # Get updated training stats
        stats = service.get_training_stats()

        return SubmitCorrectionsResponse(
            success=True,
            saved_count=saved_count,
            error_count=error_count,
            message=f"Saved {saved_count} corrections. Training data updated.",
            training_stats=stats,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving corrections: {str(e)}")


@router.get("/stats", response_model=TrainingStatsResponse)
def get_training_stats(
    auction_type_id: Optional[int] = None, session: Session = Depends(get_session)
):
    """
    Get training statistics for all auction types or a specific one.
    """
    service = TrainingService(session)
    stats = service.get_training_stats(auction_type_id)
    return TrainingStatsResponse(**stats)


@router.get("/rules/{auction_type_id}", response_model=list[RuleResponse])
def get_extraction_rules(
    auction_type_id: int, field_key: Optional[str] = None, session: Session = Depends(get_session)
):
    """
    Get extraction rules for an auction type.
    """
    service = TrainingService(session)
    rules = service.get_extraction_rules(auction_type_id, field_key)

    return [
        RuleResponse(
            id=r.id,
            field_key=r.field_key,
            rule_type=r.rule_type,
            label_patterns=r.get_label_patterns(),
            exclude_patterns=r.get_exclude_patterns(),
            confidence=r.confidence,
            validation_count=r.validation_count,
            is_active=r.is_active,
        )
        for r in rules
    ]


@router.get("/rules-for-extractor/{auction_type_code}")
def get_rules_for_extractor(auction_type_code: str, session: Session = Depends(get_session)):
    """
    Get extraction rules in format suitable for extractors.
    """
    service = TrainingService(session)
    return service.get_rules_for_extractor(auction_type_code)


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    """
    Deactivate an extraction rule.
    """

    rule = session.get(ExtractionRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_active = False
    session.commit()

    return {"success": True, "message": "Rule deactivated"}
