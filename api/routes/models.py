"""
Models API Routes

Manage ML model versions and training jobs.
"""

import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from api.models import (
    AuctionTypeRepository,
    ModelVersionRepository,
    TrainingJobRepository,
)

router = APIRouter(prefix="/api/models", tags=["Models"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class ModelVersionResponse(BaseModel):
    """Model version info."""

    id: int
    uuid: str
    auction_type_id: int
    auction_type_code: Optional[str] = None
    version_tag: str
    base_model: str = "microsoft/layoutlmv3-base"
    adapter_path: Optional[str] = None
    status: str = "training"
    metrics_json: Optional[dict] = None
    training_job_id: Optional[int] = None
    created_at: Optional[str] = None
    promoted_at: Optional[str] = None

    class Config:
        from_attributes = True


class ModelVersionListResponse(BaseModel):
    """List of model versions."""

    items: list[ModelVersionResponse]
    total: int


class TrainingJobRequest(BaseModel):
    """Request to start a training job."""

    auction_type_id: int = Field(..., description="Auction type to train for")
    version_tag: Optional[str] = Field(
        None, description="Version tag (auto-generated if not provided)"
    )
    base_model: str = Field("microsoft/layoutlmv3-base", description="Base model to fine-tune")
    epochs: int = Field(3, ge=1, le=20, description="Training epochs")
    learning_rate: float = Field(2e-5, description="Learning rate")
    batch_size: int = Field(4, ge=1, le=32, description="Batch size")


class TrainingJobResponse(BaseModel):
    """Training job info."""

    id: int
    uuid: str
    auction_type_id: int
    auction_type_code: Optional[str] = None
    model_version_id: Optional[int] = None
    status: str = "pending"
    config_json: Optional[dict] = None
    metrics_json: Optional[dict] = None
    log_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class TrainingJobListResponse(BaseModel):
    """List of training jobs."""

    items: list[TrainingJobResponse]
    total: int


class TrainingDataStats(BaseModel):
    """Statistics about training data."""

    auction_type_id: int
    auction_type_code: str
    total_examples: int
    correct_examples: int
    incorrect_examples: int
    unique_fields: int
    unique_documents: int
    ready_for_training: bool


# =============================================================================
# TRAINING LOGIC (PLACEHOLDER FOR ML)
# =============================================================================


def run_training_job(job_id: int, auction_type_id: int, config: dict):
    """
    Execute a training job.

    NOTE: This is a placeholder. Real implementation would:
    1. Load training examples for the auction type
    2. Initialize PEFT/LoRA adapter
    3. Fine-tune on training data
    4. Evaluate and save metrics
    5. Save adapter weights
    """

    # Update status to running
    TrainingJobRepository.update(job_id, status="running")

    try:
        # Simulate training (placeholder)
        time.sleep(2)

        # Check if we have training data
        from api.database import get_connection

        with get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM training_examples WHERE auction_type_id = ?",
                (auction_type_id,),
            ).fetchone()[0]

        if count < 10:
            raise ValueError(f"Insufficient training examples: {count} (need >= 10)")

        # Simulate metrics
        metrics = {
            "train_loss": 0.15,
            "eval_loss": 0.18,
            "accuracy": 0.92,
            "f1": 0.89,
            "examples_used": count,
            "epochs": config.get("epochs", 3),
        }

        # Create or update model version
        job = TrainingJobRepository.get_by_id(job_id)
        if not job.model_version_id:
            version_tag = config.get("version_tag", f"v{int(time.time())}")
            model_id = ModelVersionRepository.create(
                auction_type_id=auction_type_id,
                version_tag=version_tag,
                base_model=config.get("base_model", "microsoft/layoutlmv3-base"),
                training_job_id=job_id,
            )
            TrainingJobRepository.update(job_id, model_version_id=model_id)
        else:
            model_id = job.model_version_id

        # Update model with metrics
        ModelVersionRepository.update(
            model_id,
            status="ready",
            metrics_json=metrics,
            adapter_path=f"/models/adapters/{auction_type_id}/{config.get('version_tag', 'latest')}",
        )

        # Complete job
        TrainingJobRepository.update(
            job_id,
            status="completed",
            metrics_json=metrics,
        )

    except Exception as e:
        TrainingJobRepository.update(
            job_id,
            status="failed",
            error_message=str(e),
        )


# =============================================================================
# ROUTES - MODEL VERSIONS
# =============================================================================


@router.get("/versions", response_model=ModelVersionListResponse)
async def list_model_versions(
    auction_type_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List model versions with optional filtering."""
    from api.database import get_connection

    sql = "SELECT * FROM model_versions WHERE 1=1"
    params = []

    if auction_type_id:
        sql += " AND auction_type_id = ?"
        params.append(auction_type_id)
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM model_versions WHERE 1=1").fetchone()[0]

    items = []
    for row in rows:
        data = dict(row)
        at = AuctionTypeRepository.get_by_id(data["auction_type_id"])

        if data.get("metrics_json"):
            import json

            data["metrics_json"] = json.loads(data["metrics_json"])

        items.append(
            ModelVersionResponse(
                id=data["id"],
                uuid=data["uuid"],
                auction_type_id=data["auction_type_id"],
                auction_type_code=at.code if at else None,
                version_tag=data["version_tag"],
                base_model=data["base_model"],
                adapter_path=data.get("adapter_path"),
                status=data["status"],
                metrics_json=data.get("metrics_json"),
                training_job_id=data.get("training_job_id"),
                created_at=data.get("created_at"),
                promoted_at=data.get("promoted_at"),
            )
        )

    return ModelVersionListResponse(items=items, total=total)


@router.get("/versions/active/{auction_type_id}", response_model=ModelVersionResponse)
async def get_active_model(auction_type_id: int):
    """Get the active model version for an auction type."""
    model = ModelVersionRepository.get_active(auction_type_id)
    if not model:
        raise HTTPException(status_code=404, detail="No active model for this auction type")

    at = AuctionTypeRepository.get_by_id(model.auction_type_id)

    return ModelVersionResponse(
        id=model.id,
        uuid=model.uuid,
        auction_type_id=model.auction_type_id,
        auction_type_code=at.code if at else None,
        version_tag=model.version_tag,
        base_model=model.base_model,
        adapter_path=model.adapter_path,
        status=model.status,
        metrics_json=model.metrics_json,
        training_job_id=model.training_job_id,
        created_at=model.created_at,
        promoted_at=model.promoted_at,
    )


@router.post("/versions/{model_id}/promote", response_model=ModelVersionResponse)
async def promote_model(model_id: int):
    """
    Promote a model version to active status.

    This deactivates any other active model for the same auction type.
    """
    model = ModelVersionRepository.get_by_id(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model version not found")

    if model.status not in ("ready", "active"):
        raise HTTPException(
            status_code=400, detail=f"Cannot promote model in {model.status} status"
        )

    # Promote (this deactivates other models)
    ModelVersionRepository.promote(model_id)

    # Get updated model
    model = ModelVersionRepository.get_by_id(model_id)
    at = AuctionTypeRepository.get_by_id(model.auction_type_id)

    return ModelVersionResponse(
        id=model.id,
        uuid=model.uuid,
        auction_type_id=model.auction_type_id,
        auction_type_code=at.code if at else None,
        version_tag=model.version_tag,
        base_model=model.base_model,
        adapter_path=model.adapter_path,
        status=model.status,
        metrics_json=model.metrics_json,
        training_job_id=model.training_job_id,
        created_at=model.created_at,
        promoted_at=model.promoted_at,
    )


@router.delete("/versions/{model_id}")
async def archive_model(model_id: int):
    """Archive a model version (soft delete)."""
    model = ModelVersionRepository.get_by_id(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model version not found")

    if model.status == "active":
        raise HTTPException(
            status_code=400, detail="Cannot archive active model. Promote another model first."
        )

    ModelVersionRepository.update(model_id, status="archived")

    return {"id": model_id, "status": "archived", "message": "Model archived"}


# =============================================================================
# ROUTES - TRAINING JOBS
# =============================================================================


@router.post("/train", status_code=501)
async def start_training(
    data: TrainingJobRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="Run synchronously (wait for completion)"),
):
    """
    Start a new training job.

    NOTE: ML training is NOT IMPLEMENTED in MVP.
    This endpoint is for data collection phase only.

    The review workflow collects training examples that will be used
    for future PEFT/LoRA fine-tuning once sufficient data is gathered.
    """
    # MVP: Return 501 Not Implemented with roadmap link
    # Training is disabled - this is data collection phase only
    from api.database import get_connection

    # Still provide stats about training data availability
    with get_connection() as conn:
        example_count = conn.execute(
            "SELECT COUNT(*) FROM training_examples WHERE auction_type_id = ?",
            (data.auction_type_id,),
        ).fetchone()[0]

    raise HTTPException(
        status_code=501,
        detail={
            "message": "ML training is not implemented in MVP",
            "phase": "data_collection",
            "training_examples_collected": example_count,
            "minimum_required": 100,
            "roadmap": "PEFT/LoRA fine-tuning will be implemented when sufficient training data is collected (100+ examples per auction type)",
            "current_status": "Use the review workflow to collect and validate training examples. Rule-based extraction is active.",
        },
    )


@router.get("/jobs", response_model=TrainingJobListResponse)
async def list_training_jobs(
    auction_type_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List training jobs with optional filtering."""
    from api.database import get_connection

    sql = "SELECT * FROM training_jobs WHERE 1=1"
    params = []

    if auction_type_id:
        sql += " AND auction_type_id = ?"
        params.append(auction_type_id)
    if status:
        sql += " AND status = ?"
        params.append(status)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM training_jobs WHERE 1=1").fetchone()[0]

    items = []
    for row in rows:
        data = dict(row)
        at = AuctionTypeRepository.get_by_id(data["auction_type_id"])

        if data.get("config_json"):
            import json

            data["config_json"] = json.loads(data["config_json"])
        if data.get("metrics_json"):
            import json

            data["metrics_json"] = json.loads(data["metrics_json"])

        items.append(
            TrainingJobResponse(
                id=data["id"],
                uuid=data["uuid"],
                auction_type_id=data["auction_type_id"],
                auction_type_code=at.code if at else None,
                model_version_id=data.get("model_version_id"),
                status=data["status"],
                config_json=data.get("config_json"),
                metrics_json=data.get("metrics_json"),
                log_path=data.get("log_path"),
                error_message=data.get("error_message"),
                created_at=data.get("created_at"),
                started_at=data.get("started_at"),
                completed_at=data.get("completed_at"),
            )
        )

    return TrainingJobListResponse(items=items, total=total)


@router.get("/jobs/{job_id}", response_model=TrainingJobResponse)
async def get_training_job(job_id: int):
    """Get details of a training job."""
    job = TrainingJobRepository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    at = AuctionTypeRepository.get_by_id(job.auction_type_id)

    return TrainingJobResponse(
        id=job.id,
        uuid=job.uuid,
        auction_type_id=job.auction_type_id,
        auction_type_code=at.code if at else None,
        model_version_id=job.model_version_id,
        status=job.status,
        config_json=job.config_json,
        metrics_json=job.metrics_json,
        log_path=job.log_path,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_training_job(job_id: int):
    """Cancel a running training job."""
    job = TrainingJobRepository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in {job.status} status")

    TrainingJobRepository.update(job_id, status="cancelled")

    return {"id": job_id, "status": "cancelled", "message": "Training job cancelled"}


# =============================================================================
# ROUTES - TRAINING DATA STATS
# =============================================================================


class TrainingStatsOverview(BaseModel):
    """Overview of training stats across all auction types."""

    total_examples: int
    total_validated: int
    by_auction_type: dict


@router.get("/training-stats/overview")
async def get_training_stats_overview():
    """Get training stats overview for the Test Lab dashboard."""
    from sqlmodel import Session, select

    from api.database import get_connection
    from api.training_db import engine
    from models.training import FieldCorrection, TrainingExample

    # Get auction types from main database
    with get_connection() as conn:
        auction_types = conn.execute(
            "SELECT id, code FROM auction_types WHERE is_active = TRUE"
        ).fetchall()

    by_auction_type = {}
    total_examples = 0
    total_validated = 0

    # Query training database for stats
    with Session(engine) as session:
        for at in auction_types:
            at_id = at["id"]
            at_code = at["code"]

            # Count from training_examples in training.db
            try:
                examples = session.exec(
                    select(TrainingExample).where(TrainingExample.auction_type_id == at_id)
                ).all()
                total = len(examples)
                validated = sum(1 for ex in examples if ex.is_validated)
            except Exception:
                total = 0
                validated = 0

            # Count unique runs from field_corrections in training.db
            try:
                corrections = session.exec(
                    select(FieldCorrection).where(FieldCorrection.auction_type_id == at_id)
                ).all()
                unique_runs = len({c.extraction_run_id for c in corrections})
                # Add unique correction runs to totals (deduplicated with examples)
                if unique_runs > total:
                    total = unique_runs
                    validated = unique_runs
            except Exception:
                pass

            by_auction_type[at_code] = {
                "total": total,
                "validated": validated,
            }

            total_examples += total
            total_validated += validated

    return {
        "total_examples": total_examples,
        "total_validated": total_validated,
        "by_auction_type": by_auction_type,
    }


@router.get("/training-stats", response_model=list[TrainingDataStats])
async def get_training_stats():
    """
    Get training data statistics per auction type.

    Shows which auction types have enough data for training.
    Reads from training.db (separate training database).
    """
    from sqlmodel import Session, select

    from api.database import get_connection
    from api.training_db import engine
    from models.training import ExtractionRule, FieldCorrection, TrainingExample

    # Get auction types from main database
    with get_connection() as conn:
        auction_types = conn.execute(
            "SELECT id, code FROM auction_types WHERE is_active = TRUE"
        ).fetchall()

    stats = []

    # Query training database for stats
    with Session(engine) as session:
        for at in auction_types:
            at_id = at["id"]
            at_code = at["code"]

            # Count training examples from training.db
            total_examples = session.exec(
                select(TrainingExample).where(TrainingExample.auction_type_id == at_id)
            ).all()
            total = len(total_examples)

            # Count validated examples
            validated = sum(1 for ex in total_examples if ex.is_validated)
            incorrect = total - validated

            # Count unique documents
            unique_doc_ids = {ex.document_id for ex in total_examples}
            unique_docs = len(unique_doc_ids)

            # Count field corrections
            corrections = session.exec(
                select(FieldCorrection).where(FieldCorrection.auction_type_id == at_id)
            ).all()
            correction_count = len(corrections)

            # Count unique fields from corrections
            unique_field_keys = {c.field_key for c in corrections}
            unique_fields = len(unique_field_keys)

            # Count extraction rules
            rules = session.exec(
                select(ExtractionRule)
                .where(ExtractionRule.auction_type_id == at_id)
                .where(ExtractionRule.is_active)
            ).all()
            rules_count = len(rules)

            # Calculate average confidence
            avg_confidence = 0.0
            if rules:
                avg_confidence = sum(r.confidence for r in rules) / len(rules)

            stats.append(
                TrainingDataStats(
                    auction_type_id=at_id,
                    auction_type_code=at_code,
                    total_examples=total,
                    correct_examples=validated,
                    incorrect_examples=incorrect,
                    unique_fields=unique_fields if unique_fields > 0 else correction_count,
                    unique_documents=unique_docs,
                    ready_for_training=total >= 10,
                    # Additional stats
                    rules_count=rules_count if hasattr(TrainingDataStats, "rules_count") else None,
                    avg_confidence=(
                        avg_confidence if hasattr(TrainingDataStats, "avg_confidence") else None
                    ),
                )
            )

    return stats
