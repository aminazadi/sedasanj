from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import defer

from app.deps import OrgAdminDep, TenantSession, client_ip
from app.errors import ApiError
from app.models import ScheduledReport, ScheduledReportRun, Tenant
from app.services import audit
from app.services.scheduled_reports import create_run, next_run_at

router = APIRouter(prefix="/v1/scheduled-reports", tags=["scheduled reports"])


class ReportInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=2, max_length=12000)
    enabled: bool = True
    schedule_mode: Literal["interval", "fixed"] = "interval"
    interval_hours: int | None = Field(default=24, ge=1, le=8760)
    fixed_hours: list[int] = Field(default_factory=list, max_length=24)
    max_retries: int = Field(default=3, ge=0, le=3)
    retry_base_minutes: int = Field(default=5, ge=1, le=60)

    @model_validator(mode="after")
    def validate_schedule(self) -> ReportInput:
        if self.schedule_mode == "interval":
            if self.interval_hours is None or self.fixed_hours:
                raise ValueError("interval mode requires interval_hours and no fixed_hours")
        elif (
            self.interval_hours is not None
            or not self.fixed_hours
            or any(h < 0 or h > 23 for h in self.fixed_hours)
            or len(set(self.fixed_hours)) != len(self.fixed_hours)
        ):
            raise ValueError(
                "fixed mode requires unique hours from 0 to 23 and interval_hours=null"
            )
        self.fixed_hours.sort()
        return self


class ReportOut(ReportInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    next_run_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    report_id: UUID
    name: str
    trigger: str
    status: str
    from_date: datetime
    to_date: datetime
    created_at: datetime
    error_code: str | None
    error_detail: str | None
    attempt_count: int
    max_retries: int
    next_attempt_at: datetime | None
    coverage: dict = Field(default_factory=dict)


class RunOut(RunSummary):
    instructions: str
    timezone: str
    content: str | None
    sources: list[dict]
    coverage: dict
    memory_snapshot: list[dict]
    model: str | None
    started_at: datetime | None
    completed_at: datetime | None


class RunPage(BaseModel):
    total: int
    items: list[RunSummary]


class RunRequest(BaseModel):
    idempotency_key: UUID


async def get_report(session, tenant_id: UUID, report_id: UUID, *, lock=False):
    query = select(ScheduledReport).where(
        ScheduledReport.id == report_id, ScheduledReport.tenant_id == tenant_id
    )
    if lock:
        query = query.with_for_update()
    row = (await session.execute(query)).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "report not found")
    return row


@router.get("", response_model=list[ReportOut])
async def list_reports(principal: OrgAdminDep, session: TenantSession, archived: bool = False):
    query = select(ScheduledReport).where(ScheduledReport.tenant_id == principal.tenant_id)
    query = query.where(
        ScheduledReport.archived_at.is_not(None)
        if archived
        else ScheduledReport.archived_at.is_(None)
    )
    return (
        (await session.execute(query.order_by(ScheduledReport.created_at.desc()))).scalars().all()
    )


@router.post("", response_model=ReportOut, status_code=201)
async def add_report(
    payload: ReportInput, request: Request, principal: OrgAdminDep, session: TenantSession
):
    now = datetime.now(UTC)
    tenant = await session.get(Tenant, principal.tenant_id)
    row = ScheduledReport(
        tenant_id=principal.tenant_id,
        created_by=principal.id,
        window_start=now,
        **payload.model_dump(),
    )
    row.next_run_at = next_run_at(row, now, tenant.timezone) if row.enabled else None
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="scheduled_report.create",
        payload={"report_id": str(row.id)},
        ip=client_ip(request),
    )
    return row


@router.put("/{report_id}", response_model=ReportOut)
async def edit_report(
    report_id: UUID,
    payload: ReportInput,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
):
    row = await get_report(session, principal.tenant_id, report_id, lock=True)
    if row.archived_at is not None:
        raise ApiError("invalid_request", "archived report cannot be edited")
    now = datetime.now(UTC)
    changed = (row.schedule_mode, row.interval_hours, row.fixed_hours) != (
        payload.schedule_mode,
        payload.interval_hours,
        payload.fixed_hours,
    )
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    tenant = await session.get(Tenant, principal.tenant_id)
    if not row.enabled:
        row.next_run_at = None
    elif changed or (payload.enabled and row.next_run_at is None):
        row.next_run_at = next_run_at(row, now, tenant.timezone)
    row.updated_at = now
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="scheduled_report.update",
        payload={"report_id": str(row.id)},
        ip=client_ip(request),
    )
    return row


@router.delete("/{report_id}", status_code=204)
async def archive_report(
    report_id: UUID, request: Request, principal: OrgAdminDep, session: TenantSession
):
    row = await get_report(session, principal.tenant_id, report_id, lock=True)
    row.enabled = False
    row.next_run_at = None
    row.archived_at = row.archived_at or datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="scheduled_report.archive",
        payload={"report_id": str(row.id)},
        ip=client_ip(request),
    )


@router.post("/{report_id}/run", response_model=RunOut, status_code=202)
async def run_now(
    report_id: UUID,
    payload: RunRequest,
    request: Request,
    principal: OrgAdminDep,
    session: TenantSession,
):
    row = await get_report(session, principal.tenant_id, report_id, lock=True)
    existing = (
        await session.execute(
            select(ScheduledReportRun).where(
                ScheduledReportRun.report_id == row.id,
                ScheduledReportRun.tenant_id == principal.tenant_id,
                ScheduledReportRun.idempotency_key == str(payload.idempotency_key),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    if row.archived_at is not None:
        raise ApiError("invalid_request", "archived report cannot be executed")
    active = (
        await session.execute(
            select(ScheduledReportRun.id).where(
                ScheduledReportRun.report_id == row.id,
                ScheduledReportRun.status.in_(("queued", "running")),
            )
        )
    ).scalar_one_or_none()
    if active:
        raise ApiError("conflict_idempotency", "a report is already queued or running")
    tenant = await session.get(Tenant, principal.tenant_id)
    run = await create_run(
        session,
        row,
        datetime.now(UTC),
        tenant.timezone,
        "manual",
        str(payload.idempotency_key),
        principal.id,
    )
    await audit.record(
        session,
        actor_type="user",
        actor_id=principal.id,
        tenant_id=principal.tenant_id,
        action="scheduled_report.run",
        payload={"report_id": str(row.id), "run_id": str(run.id)},
        ip=client_ip(request),
    )
    return run


@router.get("/runs", response_model=RunPage)
async def list_runs(
    principal: OrgAdminDep,
    session: TenantSession,
    report_id: UUID | None = None,
    status: Literal["queued", "running", "succeeded", "failed"] | None = None,
    trigger: Literal["scheduled", "manual"] | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
):
    filters = [ScheduledReportRun.tenant_id == principal.tenant_id]
    if report_id:
        filters.append(ScheduledReportRun.report_id == report_id)
    if status:
        filters.append(ScheduledReportRun.status == status)
    if trigger:
        filters.append(ScheduledReportRun.trigger == trigger)
    total = (
        await session.execute(select(func.count()).select_from(ScheduledReportRun).where(*filters))
    ).scalar_one()
    rows = (
        (
            await session.execute(
                select(ScheduledReportRun)
                .options(
                    defer(ScheduledReportRun.memory_snapshot),
                    defer(ScheduledReportRun.content),
                    defer(ScheduledReportRun.sources),
                    defer(ScheduledReportRun.instructions),
                )
                .where(*filters)
                .order_by(ScheduledReportRun.created_at.desc(), ScheduledReportRun.id)
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "items": [RunSummary.model_validate(row).model_dump(mode="json") for row in rows],
    }


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: UUID, principal: OrgAdminDep, session: TenantSession):
    row = (
        await session.execute(
            select(ScheduledReportRun).where(
                ScheduledReportRun.id == run_id, ScheduledReportRun.tenant_id == principal.tenant_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("not_found", "report run not found")
    return row
