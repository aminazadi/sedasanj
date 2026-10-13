from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalysisRun
from app.services.organization_memory import build_context
from app.services.platform import capability_model, effective_extract_prompt, effective_models


async def create(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    call_id: UUID,
    status: str,
    result: dict[str, Any] | None = None,
) -> AnalysisRun:
    models = await effective_models(session)
    memory = await build_context(session, tenant_id, "analysis")
    scoring = await build_context(session, tenant_id, "scoring")
    snapshot = dict(memory.snapshot)
    snapshot["scoring_items"] = scoring.snapshot["items"]
    snapshot["scoring_context"] = scoring.text
    return AnalysisRun(
        call_id=call_id,
        tenant_id=tenant_id,
        llm_model=capability_model(models, "analysis"),
        ai_provider=models.get("analysis_provider", "aiservice"),
        decision_provider=models.get("decision_provider", "aiservice"),
        decision_model=capability_model(models, "decision"),
        prompt_version=models["prompt_version"],
        system_prompt=await effective_extract_prompt(session, models["prompt_version"]),
        memory_snapshot=snapshot,
        memory_context=memory.text,
        memory_sha256=memory.sha256,
        status=status,
        result=result,
    )


async def ensure_snapshot(session: AsyncSession, run: AnalysisRun) -> None:
    if run.memory_snapshot is not None:
        return
    memory = await build_context(session, run.tenant_id, "analysis")
    scoring = await build_context(session, run.tenant_id, "scoring")
    run.memory_snapshot = {
        **memory.snapshot,
        "scoring_items": scoring.snapshot["items"],
        "scoring_context": scoring.text,
    }
    run.memory_context = memory.text
    run.memory_sha256 = memory.sha256
