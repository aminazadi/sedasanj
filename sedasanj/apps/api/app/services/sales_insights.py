from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisRun, KpiConfiguration, SalesInsight
from app.schemas import ExtractionResult


async def sync_from_extraction(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    analysis_run_id: UUID,
    result: ExtractionResult,
) -> SalesInsight:
    configuration = (
        await session.execute(
            select(KpiConfiguration)
            .where(KpiConfiguration.tenant_id == tenant_id, KpiConfiguration.active.is_(True))
            .order_by(KpiConfiguration.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    settings = configuration.settings if configuration else {}
    taxonomy_version = int(settings.get("taxonomy_version", 1))
    analysis_run = await session.get(AnalysisRun, analysis_run_id)
    if analysis_run is not None:
        analysis_result = dict(analysis_run.result or result.model_dump(mode="json"))
        analysis_result["taxonomy_version"] = taxonomy_version
        analysis_run.result = analysis_result
    allowed_stages = set(
        settings.get(
            "funnel_stages",
            ["effective", "qualified", "interested", "follow_up", "proposal", "won", "lost"],
        )
    )
    allowed_objections = set(
        settings.get(
            "objection_taxonomy",
            ["price", "trust", "timing", "competitor", "no_need", "other"],
        )
    )
    row = await session.get(SalesInsight, call_id)
    if row is None:
        row = SalesInsight(call_id=call_id, tenant_id=tenant_id)
        session.add(row)
    sales = result.sales
    row.analysis_run_id = analysis_run_id
    row.taxonomy_version = taxonomy_version
    row.funnel_stage = sales.funnel_stage if sales.funnel_stage in allowed_stages else "unknown"
    row.outcome = sales.outcome
    row.certainty = sales.certainty
    row.confidence = sales.confidence
    row.product = sales.product
    row.objections = [
        objection if objection in allowed_objections else "other" for objection in sales.objections
    ]
    row.win_loss_reason = sales.win_loss_reason
    row.next_action = sales.next_action
    row.next_action_due_at = sales.next_action_due_at
    row.evidence = [item.model_dump(mode="json") for item in sales.evidence]
    row.updated_at = datetime.now(UTC)
    return row
