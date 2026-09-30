from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import session_scope
from app.models import AnalysisRun, Call, OperatorCallScore, OperatorScoreRubric, Transcript, User
from app.services.aiservice_decision import AiServiceDecisionClient
from app.services.operator_scope import number_matches
from app.services.platform import effective_models, resolve_provider_settings


async def score_call(tenant_id: UUID, call_id: UUID, analysis_run_id: UUID) -> str:
    async with session_scope(tenant_id) as session:
        existing = (await session.execute(select(OperatorCallScore).where(OperatorCallScore.call_id == call_id, OperatorCallScore.analysis_run_id == analysis_run_id))).scalar_one_or_none()
        if existing is not None:
            return existing.status
        call = await session.get(Call, call_id)
        run = await session.get(AnalysisRun, analysis_run_id)
        transcript = await session.get(Transcript, call_id)
        if call is None or run is None or transcript is None:
            return "ineligible"
        users = (await session.execute(select(User).where(User.tenant_id == tenant_id, User.role == "operator"))).scalars().all()
        matched = [user for user in users if number_matches(call.agent_extension, [value for value in (user.extension, user.mobile_number) if value])]
        label = f"اپراتور داخلی {call.agent_extension}" if call.agent_extension else "اپراتور نامشخص"
        if len(matched) != 1:
            session.add(OperatorCallScore(tenant_id=tenant_id, call_id=call_id, analysis_run_id=analysis_run_id, operator_id=None, operator_label=label, model=run.llm_model, status="ineligible"))
            return "ineligible"
        operator = matched[0]
        label = operator.display_name or (f"اپراتور داخلی {operator.extension}" if operator.extension else operator.email)
        rubric = (await session.execute(select(OperatorScoreRubric).where(OperatorScoreRubric.tenant_id == tenant_id, OperatorScoreRubric.active.is_(True)).order_by(OperatorScoreRubric.version.desc()).limit(1))).scalar_one_or_none()
        if rubric is None:
            criteria = [
                {"title": "برخورد حرفه‌ای", "description": "لحن محترمانه و حرفه‌ای", "weight": 20, "levels": ["رفتار نامناسب یا توهین‌آمیز", "لحن ضعیف", "رفتار قابل‌قبول", "محترمانه و حرفه‌ای", "کاملاً حرفه‌ای و مسئولانه"]},
                {"title": "درک مسئله", "description": "فهم درست درخواست مشتری", "weight": 20, "levels": ["درک نکرد", "برداشت نادرست", "درک ناقص", "درک درست", "درک دقیق جزئیات"]},
                {"title": "دقت پاسخ", "description": "پاسخ روشن و درست", "weight": 20, "levels": ["نادرست", "عمدتاً نادرست", "ناقص", "درست و روشن", "دقیق و کامل"]},
                {"title": "همدلی", "description": "همدلی و همراهی با مشتری", "weight": 20, "levels": ["بی‌توجه", "همدلی بسیار کم", "همدلی محدود", "همدل", "همدلی فعال"]},
                {"title": "پیگیری", "description": "جمع‌بندی و گام بعدی", "weight": 20, "levels": ["بدون پیگیری", "نامشخص", "ناقص", "گام بعدی روشن", "جمع‌بندی کامل و مسئولانه"]},
            ]
            rubric = OperatorScoreRubric(tenant_id=tenant_id, version=1, criteria=criteria, active=True)
            session.add(rubric)
            await session.flush()
        score = OperatorCallScore(tenant_id=tenant_id, call_id=call_id, analysis_run_id=analysis_run_id, rubric_id=rubric.id, operator_id=operator.id, operator_label=label, model=run.llm_model, status="running")
        session.add(score)
        await session.flush()
        text = (transcript.corrected_text or transcript.full_text)[:12000]
        criteria = list(rubric.criteria)
        models = await effective_models(session)
        runtime = await resolve_provider_settings(session)
    try:
        questions = {
            f"criterion_{index}": {
                "type": "score",
                "instructions": f"عملکرد اپراتور را فقط درباره «{item['title']}» ارزیابی کن: {item['description']}",
                "criteria": item.get("levels") or ["ضعیف", "متوسط", "خوب", "عالی", "برجسته"],
            }
            for index, item in enumerate(criteria)
        }
        client = AiServiceDecisionClient(runtime, request_namespace=str(score.id))
        try:
            primary = await client.decide(model=models["decision_model"], state={"transcript": text, "subject": "operator_performance"}, questions=questions)
            if any(
                not isinstance(answer, dict) or answer.get("abstained")
                for answer in primary["answers"].values()
            ):
                fallback = await client.decide(model=models["decision_fallback_model"], state={"transcript": text, "subject": "operator_performance"}, questions=questions)
                for key, answer in fallback["answers"].items():
                    if primary["answers"].get(key, {}).get("abstained") is True and not answer.get("abstained"):
                        primary["answers"][key] = answer
        finally:
            await client.close()
        accepted: list[dict[str, Any]] = []
        weighted = 0.0
        needs_review = False
        answers = primary["answers"]
        for index, item in enumerate(criteria):
            answer = answers.get(f"criterion_{index}")
            if not isinstance(answer, dict) or answer.get("abstained") or answer.get("answer") is None:
                needs_review = True
                continue
            level = max(0.0, min(4.0, float(answer["answer"])))
            value = level * 25.0
            accepted.append({"title": str(item["title"]), "score": value, "level": level, "confidence": float(answer.get("confidence") or 0), "probabilities": answer.get("probabilities") or {}})
            raw_weight = item.get("weight")
            if isinstance(raw_weight, bool) or not isinstance(
                raw_weight, (int, float, str)
            ):
                needs_review = True
                continue
            try:
                weight = int(raw_weight)
            except (TypeError, ValueError):
                needs_review = True
                continue
            if weight < 0 or weight > 100:
                needs_review = True
                continue
            weighted += value * weight
        total = weighted / 100 if len(accepted) == len(criteria) else None
        status_value = "needs_review" if needs_review else "succeeded"
        async with session_scope(tenant_id) as session:
            saved = await session.get(OperatorCallScore, score.id)
            if saved is not None:
                saved.status = status_value
                saved.total_score = total
                saved.criteria_scores = accepted
                saved.completed_at = datetime.now(UTC)
        return status_value
    except Exception as exc:
        async with session_scope(tenant_id) as session:
            saved = await session.get(OperatorCallScore, score.id)
            if saved is not None:
                saved.status = "failed"
                saved.error_detail = repr(exc)[:1000]
                saved.completed_at = datetime.now(UTC)
        return "failed"
