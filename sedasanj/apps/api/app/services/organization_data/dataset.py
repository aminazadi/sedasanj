from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5
from zipfile import ZipFile

from sqlalchemy import Table, bindparam, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.errors import ApiError
from app.models import Base, Tenant, User
from app.services.assistant_export_renderers import MEDIA_TYPES
from app.services.organization_data import archive as binary
from app.services.storage import Storage, get_storage

# Parent tables precede children. The memory chain is ordered by revision within its table.
TABLE_NAMES = (
    "audio_objects",
    "calls",
    "contacts",
    "pbx_extensions",
    "teams",
    "team_memberships",
    "call_operator_assignments",
    "utterances",
    "asr_transcript_revisions",
    "asr_transcript_revision_segments",
    "transcript_revisions",
    "transcript_revision_segments",
    "transcripts",
    "analysis_runs",
    "analysis_steps",
    "call_insights",
    "sales_insights",
    "kpi_configurations",
    "kpi_goals",
    "crm_outcomes",
    "operator_score_rubrics",
    "operator_call_scores",
    "operator_call_coachings",
    "call_knowledge",
    "chat_conversations",
    "assistant_exports",
    "chat_messages",
    "assistant_tool_runs",
    "organization_memories",
    "follow_up_tasks",
    "follow_up_task_events",
    "meetings",
    "meeting_chunks",
    "meeting_segments",
    "meeting_chunk_speakers",
    "meeting_speakers",
    "meeting_attendees",
    "meeting_analysis_steps",
    "meeting_minutes",
    "meeting_events",
    "tenant_ai_instructions",
    "scheduled_reports",
    "scheduled_report_runs",
)
TABLES = {name: Base.metadata.tables[name] for name in TABLE_NAMES}
TERMINAL = {
    "calls": {"complete", "failed_terminal", "failed_retryable", "canceled", "missed"},
    "meetings": {"complete", "failed_terminal", "failed_retryable", "canceled"},
    "chat_messages": {"succeeded", "failed", "cancelled"},
    "assistant_tool_runs": {"succeeded", "failed", "cancelled"},
    "transcript_revisions": {"succeeded", "failed"},
    "asr_transcript_revisions": {"succeeded", "failed"},
    "analysis_runs": {"succeeded", "failed", "completed"},
    "analysis_steps": {"succeeded", "failed"},
    "operator_call_coachings": {"succeeded", "failed", "skipped"},
    "meeting_chunks": {"transcribed", "failed"},
    "meeting_analysis_steps": {"done", "failed"},
    "scheduled_report_runs": {"succeeded", "failed"},
}
OMIT_COLUMNS = {
    "bucket",
    "object_key",
    "storage_key",
    "provider_task_id",
    "provider_submitted_at",
    "submitted_at",
    "reserved_seconds",
    "reserved_blocks",
    "usage_id",
    "error_detail",
    "next_run_at",
    "next_attempt_at",
    "embedding",
    "embedding_model",
    "vector_status",
    "graph_status",
    "search",
    "tenant_id",
}
MEDIA_COLUMNS = {"audio_objects": "object_key", "assistant_exports": "storage_key"}
PROFILE_REFERENCES = {"meeting_speakers", "meeting_attendees"}
OPERATOR_REFERENCES = {
    ("pbx_extensions", "user_id"),
    ("meeting_speakers", "user_id"),
    ("team_memberships", "operator_id"),
    ("call_operator_assignments", "operator_id"),
    ("operator_call_scores", "operator_id"),
    ("operator_call_coachings", "operator_id"),
    ("call_knowledge", "operator_id"),
}
# A missing nullable parent normally means the row would be attached to the wrong work item.
# These historical pointers can be cleared while keeping their independent work item.
OPTIONAL_HISTORY = {
    ("chat_conversations", "call_id"),
    ("assistant_tool_runs", "assistant_message_id"),
    ("organization_memories", "source_conversation_id"),
    ("organization_memories", "source_message_id"),
    ("organization_memories", "supersedes_id"),
    ("transcripts", "active_revision_id"),
    ("transcripts", "active_asr_revision_id"),
    ("transcript_revisions", "asr_revision_id"),
    ("transcript_revision_segments", "source_utterance_id"),
}


def columns(table: Table) -> set[str]:
    return {col.name for col in table.columns if col.computed is None} - OMIT_COLUMNS


def identity(table: Table, row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(col.name) for col in table.primary_key if col.name != "tenant_id")


def member_name(table: str, row_id: str) -> str:
    try:
        return f"media/{table}/{UUID(row_id).hex}"
    except (ValueError, AttributeError, TypeError) as exc:
        raise binary.invalid_archive() from exc


async def _write_media(
    archive: ZipFile,
    storage: Storage,
    member: str,
    key: str,
    remaining: int,
) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with archive.open(binary.media_member(member), "w", force_zip64=True) as target:
        async for block in storage.iter_chunks(key):
            size += len(block)
            if size > remaining:
                raise binary.archive_too_large()
            digest.update(block)
            target.write(block)
    return size, digest.hexdigest()


def _audio_references(tenant: UUID, *, completed_only: bool = False) -> list[Any]:
    audio = TABLES["audio_objects"]
    links = []
    for name in ("calls", "meetings", "meeting_chunks"):
        parent = TABLES[name]
        query = select(parent.c.id).where(
            parent.c.tenant_id == tenant,
            parent.c.audio_id == audio.c.id,
        )
        if completed_only:
            query = query.where(parent.c.status.in_(TERMINAL[name]))
            if name == "meeting_chunks":
                meetings = TABLES["meetings"]
                query = query.where(
                    select(meetings.c.id)
                    .where(
                        meetings.c.id == parent.c.meeting_id,
                        meetings.c.tenant_id == tenant,
                        meetings.c.status.in_(TERMINAL["meetings"]),
                    )
                    .exists()
                )
        links.append(query.exists())
    return links


async def export_zip(
    tenant: UUID, path: Path, limit: int, *, gzip_payload: bool = False
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    omitted: dict[str, int] = {}
    owners: set[UUID] = set()
    media: dict[str, list[Any]] = {}
    row_hashes: dict[str, str] = {}
    seen: dict[str, set[tuple[Any, ...]]] = {}
    expanded = 0
    row_count = 0
    storage = get_storage()
    now = datetime.now(UTC)
    with binary.write_zip(path, gzip_payload=gzip_payload) as archive:
        async with session_scope(tenant, repeatable_read=True) as session:
            for name, table in TABLES.items():
                if not gzip_payload and name == "meeting_attendees":
                    continue
                included: set[tuple[Any, ...]] = set()
                seen[name] = included
                counts[name] = omitted[name] = 0
                query = select(func.to_jsonb(table.table_valued())).where(
                    table.c.tenant_id == tenant
                )
                if name == "audio_objects":
                    query = query.where(or_(*_audio_references(tenant, completed_only=True)))
                if name == "chat_messages":
                    query = query.order_by(table.c.ordinal, table.c.id)
                if name == "organization_memories":
                    query = query.order_by(table.c.version, table.c.id)
                available = columns(table)
                references = [
                    (fk.parent.name, fk.column.table.name)
                    for fk in table.foreign_keys
                    if fk.parent.name in available
                ]
                result = await session.stream_scalars(query.execution_options(yield_per=24))
                # A ZIP cannot write rows and their media members simultaneously.
                files: list[tuple[str, str, int, str | None]] = []
                row_digest = hashlib.sha256() if gzip_payload else None
                with archive.open(f"rows/{name}.ndjson", "w", force_zip64=True) as target:
                    async for row in result:
                        if name in TERMINAL and row["status"] not in TERMINAL[name]:
                            omitted[name] += 1
                            continue
                        if name == "assistant_exports" and (
                            row["deleted_at"] or datetime.fromisoformat(row["expires_at"]) <= now
                        ):
                            omitted[name] += 1
                            continue
                        if any(
                            parent in seen
                            and row[field] is not None
                            and (row[field],) not in seen[parent]
                            and (name, field) not in OPTIONAL_HISTORY
                            for field, parent in references
                        ):
                            omitted[name] += 1
                            continue
                        for field, parent in references:
                            if parent == "users" and row[field]:
                                owners.add(UUID(row[field]))
                            if (
                                (name, field) in OPTIONAL_HISTORY
                                and parent in seen
                                and (row[field],) not in seen[parent]
                            ):
                                row[field] = None
                        if gzip_payload and name in PROFILE_REFERENCES:
                            row["profile_id"] = None
                        row_count += 1
                        if row_count > binary.MAX_ROWS:
                            raise binary.archive_too_large()
                        included.add(identity(table, row))
                        if name in MEDIA_COLUMNS and not row.get("deleted_at"):
                            if name != "audio_objects" or (
                                row["expires_at"] is None
                                or datetime.fromisoformat(row["expires_at"]) > now
                            ):
                                files.append(
                                    (
                                        member_name(name, row["id"]),
                                        row[MEDIA_COLUMNS[name]],
                                        row["bytes" if name == "audio_objects" else "size_bytes"],
                                        row.get("sha256"),
                                    )
                                )
                            else:
                                row["deleted_at"] = row["expires_at"]
                        encoded = (
                            binary.json_bytes(
                                {key: row[key] for key in sorted(available) if key in row}
                            )
                            + b"\n"
                        )
                        expanded += len(encoded)
                        if len(encoded) > binary.MAX_ROW_BYTES or expanded > limit:
                            raise binary.archive_too_large()
                        if row_digest is not None:
                            row_digest.update(encoded)
                        target.write(encoded)
                        counts[name] += 1
                if row_digest is not None:
                    row_hashes[name] = row_digest.hexdigest()
                for member, key, expected_size, expected_hash in files:
                    size, digest = await _write_media(
                        archive, storage, member, key, limit - expanded
                    )
                    if size != expected_size or (expected_hash and digest != expected_hash):
                        raise binary.invalid_archive()
                    media[member] = [size, digest]
                    expanded += size
            users = (
                await session.execute(
                    select(User.id, User.email).where(User.tenant_id == tenant, User.id.in_(owners))
                )
            ).all()
            tenant_name = await session.scalar(select(Tenant.name).where(Tenant.id == tenant))
        manifest = {
            "version": 2 if gzip_payload else 1,
            "tenant_id": str(tenant),
            "organization": tenant_name,
            "owners": {str(row.id): row.email for row in users},
            "media": media,
            "counts": counts,
            "omitted": omitted,
        }
        if gzip_payload:
            manifest["row_hashes"] = row_hashes
        payload = binary.json_bytes(manifest)
        if len(payload) > binary.MAX_MANIFEST_BYTES or len(payload) + expanded > limit:
            raise binary.archive_too_large()
        archive.writestr("manifest.json", payload)
    return {"counts": counts, "omitted": omitted}


def _uuid(value: Any) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise binary.invalid_archive() from exc


def _entries(
    archive: ZipFile,
    limit: int,
    *,
    expected_version: int = 1,
) -> tuple[dict[str, Any], dict[str, list[Any]], set[str]]:
    entries = binary.checked_entries(archive, limit)
    manifest = binary.read_manifest(archive)
    media = manifest.get("media")
    owners = manifest.get("owners")
    counts = manifest.get("counts")
    if (
        manifest["version"] != expected_version
        or not isinstance(media, dict)
        or not isinstance(owners, dict)
        or len(owners) > 10_000
        or not isinstance(counts, dict)
        or any(not isinstance(v, int) or v < 0 for v in counts.values())
        or sum(counts.values()) > binary.MAX_ROWS
        or any(
            not isinstance(value, str) or len(value) > 254 or str(_uuid(key)) != key
            for key, value in owners.items()
        )
    ):
        raise binary.invalid_archive()
    for member, metadata in media.items():
        if (
            member not in entries
            or not member.startswith("media/")
            or member.split("/")[1] not in MEDIA_COLUMNS
            or not isinstance(metadata, list)
            or len(metadata) != 2
            or not isinstance(metadata[0], int)
            or metadata[0] < 0
            or metadata[0] != archive.getinfo(member).file_size
            or not isinstance(metadata[1], str)
            or len(metadata[1]) != 64
        ):
            raise binary.invalid_archive()
    allowed = {f"rows/{table}.ndjson" for table in TABLES} | {"manifest.json"} | set(media)
    if expected_version == 1:
        allowed.discard("rows/meeting_attendees.ndjson")
        if "meeting_attendees" in counts:
            raise binary.invalid_archive()
    if entries - allowed or set(counts) - set(TABLES):
        raise binary.invalid_archive()
    if expected_version == 2:
        row_hashes = manifest.get("row_hashes")
        row_members = {f"rows/{name}.ndjson" for name in counts}
        if (
            not isinstance(row_hashes, dict)
            or set(row_hashes) != set(counts)
            or row_members != entries - set(media) - {"manifest.json"}
            or any(
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
                for value in row_hashes.values()
            )
        ):
            raise binary.invalid_archive()
    return manifest, media, entries


def _read_media(
    archive: ZipFile,
    member: str,
    metadata: list[Any],
    target: Path,
) -> None:
    digest = hashlib.sha256()
    size = 0
    with archive.open(member) as incoming, target.open("wb") as outgoing:
        while block := incoming.read(binary.CHUNK_SIZE):
            size += len(block)
            if size > metadata[0]:
                raise binary.invalid_archive()
            digest.update(block)
            outgoing.write(block)
    if [size, digest.hexdigest()] != metadata:
        raise binary.invalid_archive()


def _row_batches(
    archive: ZipFile,
    member: str,
    table: Table,
    expected_sha256: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    available = columns(table)
    size = 0
    for row in binary.records(archive, member, expected_sha256):
        if set(row) - available or any(value is None for value in identity(table, row)):
            raise binary.invalid_archive()
        for col in table.primary_key:
            if col.name != "tenant_id" and col.type.python_type is UUID:
                row[col.name] = str(_uuid(row[col.name]))
        batch.append(row)
        size += len(binary.json_bytes(row))
        if len(batch) == 100 or size >= 4 * binary.CHUNK_SIZE:
            yield batch
            batch = []
            size = 0
    if batch:
        yield batch


async def _insert(
    session: AsyncSession,
    table: Table,
    rows: list[dict[str, Any]],
    *,
    assign_chat_order: bool = False,
) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    if not rows:
        return set(), set()
    pk_names = [col.name for col in table.primary_key if col.name != "tenant_id"]
    names = [col.name for col in table.columns if col.name in rows[0]]
    names_sql = ", ".join(f'"{name}"' for name in names)
    returning_sql = ", ".join(f'"{name}"' for name in pk_names)
    table_sql = f'public."{table.name}"'
    selection = names_sql
    order = ""
    if assign_chat_order:
        selection = names_sql.replace('"ordinal"', "nextval('chat_messages_ordinal_seq')")
        order = ' ORDER BY "ordinal"'

    bindings = bindparam("rows", type_=JSONB)
    # PostgreSQL casts the bounded batch using the declared column types.
    result = await session.execute(
        text(
            f"WITH inserted AS (INSERT INTO {table_sql} ({names_sql}) "
            f"SELECT {selection} FROM jsonb_populate_recordset(NULL::{table_sql}, :rows){order} "
            f"ON CONFLICT DO NOTHING RETURNING {returning_sql}) "
            "SELECT to_jsonb(inserted) FROM inserted"
        ).bindparams(bindings),
        {"rows": rows},
    )
    inserted = {identity(table, row) for row in result.scalars()}
    if len(inserted) == len(rows):
        return inserted, inserted
    predicate = " AND ".join(f't."{col.name}" = r."{col.name}"' for col in table.primary_key)
    keys = ", ".join(f't."{name}"' for name in pk_names)
    result = await session.execute(
        text(
            f"SELECT to_jsonb(matched) FROM (SELECT {keys} FROM {table_sql} t "
            f"JOIN jsonb_populate_recordset(NULL::{table_sql}, :rows) r ON {predicate} "
            "WHERE t.tenant_id = :tenant) matched"
        ).bindparams(bindings),
        {"rows": rows, "tenant": UUID(rows[0]["tenant_id"])},
    )
    return inserted, {identity(table, row) for row in result.scalars()}


def _destination_id(tenant: UUID, source: UUID, table: str, value: Any) -> str:
    uid = _uuid(value)
    return str(uid if source == tenant else uuid5(tenant, f"{source}:{table}:{uid}"))


def _references(value: Any, identities: dict[str, dict[tuple[Any, ...], tuple[Any, ...]]]) -> Any:
    if isinstance(value, list):
        return [_references(item, identities) for item in value]
    if not isinstance(value, dict):
        return value
    named = {
        "call_id": "calls",
        "contact_id": "contacts",
        "meeting_id": "meetings",
        "conversation_id": "chat_conversations",
        "message_id": "chat_messages",
        "export_id": "assistant_exports",
        "task_id": "follow_up_tasks",
    }
    result = {}
    for field, content in value.items():
        if field in named and isinstance(content, str):
            target = identities.get(named[field], {}).get((content,))
            if target:
                result[field] = target[0]
        elif field in {"call_ids", "meeting_ids"} and isinstance(content, list):
            mapped = identities.get(named[field[:-1]], {})
            result[field] = [
                mapped[(uid,)][0] for uid in content if isinstance(uid, str) and (uid,) in mapped
            ]
        elif field not in {"storage_key", "object_key", "presigned_url", "download_url"}:
            result[field] = _references(content, identities)
    return result


async def _set_defaults(
    session: AsyncSession,
    table: Table,
    tenant: UUID,
) -> dict[str, Any]:
    if table.name in {"operator_score_rubrics", "kpi_configurations"}:
        has_settings = await session.scalar(
            select(table.c.id).where(table.c.tenant_id == tenant).limit(1)
        )
        return {"active": False} if has_settings else {}
    return {}


def _restore_row(
    name: str,
    table: Table,
    original: dict[str, Any],
    identities: dict[str, dict[tuple[Any, ...], tuple[Any, ...]]],
    source: UUID,
    tenant: UUID,
    actor: UUID,
    mappings: dict[str, UUID],
    roles: dict[UUID, str],
    defaults: dict[str, Any],
) -> tuple[dict[str, Any] | None, set[str]]:
    row = {**original, "tenant_id": str(tenant), **defaults}
    if name in PROFILE_REFERENCES:
        # Portable archives retain labels and attendance, but do not restore private profiles.
        row["profile_id"] = None
    used_fallback = set()
    if name in TERMINAL and row.get("status") not in TERMINAL[name]:
        raise binary.invalid_archive()
    if "id" in table.c:
        row["id"] = _destination_id(tenant, source, name, row.get("id"))
    if "idempotency_key" in row and row["idempotency_key"] and "id" in row and source != tenant:
        row["idempotency_key"] = f"org-import:{row['id']}"
    for fk in table.foreign_keys:
        field = fk.parent.name
        value = row.get(field)
        parent = fk.column.table.name
        if field == "tenant_id" or value is None:
            continue
        value = str(_uuid(value))
        if parent == "users":
            target = mappings.get(value)
            if target is None and source == tenant and UUID(value) in roles:
                target = UUID(value)
            if (name, field) in OPERATOR_REFERENCES:
                if target is None or roles.get(target) != "operator":
                    if fk.parent.nullable:
                        row[field] = None
                        continue
                    return None, set()
            elif target is None:
                target = actor
                used_fallback.add(value)
            row[field] = str(target)
        elif parent in TABLES:
            mapped = identities.get(parent, {}).get((value,))
            if mapped is None and (name, field) not in OPTIONAL_HISTORY:
                return None, set()
            row[field] = mapped[0] if mapped else None
    for field in (
        "sources",
        "attachments",
        "filters",
        "changes",
        "structured_payload",
        "arguments",
        "result_preview",
    ):
        if field in row:
            row[field] = _references(row[field], identities)
    if name == "scheduled_reports":
        row["enabled"] = False
    elif name == "tenant_ai_instructions":
        row["updated_by_type"], row["updated_by"] = "user", str(actor)
    elif name == "call_knowledge":
        row.update(vector_status="pending", graph_status="pending", next_retry_at=None)
    elif name == "operator_call_coachings":
        row["vector_status"] = "skipped"
    elif name == "organization_memories" and source != tenant and row["status"] == "active":
        row.update(status="draft", approved_at=None, approved_by=None)
    return row, used_fallback


async def restore_zip(
    session: AsyncSession,
    archive: ZipFile,
    *,
    tenant: UUID,
    actor: UUID,
    mappings: dict[str, UUID],
    workspace: Path,
    media_prefix: str,
    expanded_limit: int,
    preview: bool,
    expected: dict[str, Any] | None = None,
    expected_version: int = 1,
) -> dict[str, Any]:
    manifest, media, entries = _entries(archive, expanded_limit, expected_version=expected_version)
    source = _uuid(manifest.get("tenant_id"))
    declared_owners = manifest["owners"]
    roles = dict(
        (await session.execute(select(User.id, User.role).where(User.tenant_id == tenant)))
        .tuples()
        .all()
    )
    if roles.get(actor) != "org_admin":
        raise ApiError("forbidden", "مدیر واردکننده باید در مقصد فعال باشد. دوباره وارد شوید.")
    if any(
        source_id not in declared_owners or target not in roles
        for source_id, target in mappings.items()
    ):
        raise ApiError("org_archive_mapping", "نگاشت اعضای مقصد را دوباره انتخاب کنید.")
    identities: dict[str, dict[tuple[Any, ...], tuple[Any, ...]]] = {}
    actual_media: set[str] = set()
    fingerprint = hashlib.sha256()
    fallback: dict[str, int] = {}
    counts: dict[str, dict[str, int]] = {}
    publish: dict[str, tuple[str, str]] = {}
    new_audio: dict[UUID, str] = {}
    storage = get_storage()
    now = datetime.now(UTC)
    settings = await session.scalar(select(Tenant.audio_retention_days).where(Tenant.id == tenant))
    for name, table in TABLES.items():
        if expected_version == 1 and name == "meeting_attendees":
            continue
        mapped: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        identities[name] = mapped
        defaults = await _set_defaults(session, table, tenant)
        totals = counts[name] = {"new": 0, "duplicate": 0, "skipped": 0}
        member = f"rows/{name}.ndjson"
        source_ids = set()
        if member not in entries:
            if manifest["counts"].get(name):
                raise binary.invalid_archive()
            continue
        for batch in _row_batches(archive, member, table, manifest.get("row_hashes", {}).get(name)):
            ready: dict[tuple[Any, ...], tuple[dict[str, Any], tuple[Any, ...], set[str]]] = {}
            # Resolve self references in version order.
            batches = ([row] for row in batch) if name == "organization_memories" else (batch,)
            for group in batches:
                ready.clear()
                for original in group:
                    source_pk = identity(table, original)
                    if any(not isinstance(key, (int, str)) for key in source_pk) or (
                        source_pk in source_ids
                    ):
                        raise binary.invalid_archive()
                    source_ids.add(source_pk)
                    if len(source_ids) > manifest["counts"].get(name, 0):
                        raise binary.invalid_archive()
                    if name in MEDIA_COLUMNS:
                        member_path = member_name(name, original["id"])
                        size_column = "bytes" if name == "audio_objects" else "size_bytes"
                        if original.get("deleted_at"):
                            if member_path in media or name != "audio_objects":
                                raise binary.invalid_archive()
                        else:
                            info = media.get(member_path)
                            if (
                                not info
                                or info[0] != original.get(size_column)
                                or (name == "audio_objects" and info[1] != original.get("sha256"))
                            ):
                                raise binary.invalid_archive()
                            actual_media.add(member_path)
                    row, used_fallback = _restore_row(
                        name,
                        table,
                        original,
                        identities,
                        source,
                        tenant,
                        actor,
                        mappings,
                        roles,
                        defaults,
                    )
                    if row is None:
                        totals["skipped"] += 1
                        fingerprint.update(binary.json_bytes([name, source_pk, "skipped"]))
                        continue
                    if name in MEDIA_COLUMNS:
                        key = f"{media_prefix}/{name}/{row['id']}"
                        row[MEDIA_COLUMNS[name]] = key
                        if name == "audio_objects":
                            row["bucket"] = storage.bucket
                            row["expires_at"] = (now + timedelta(days=settings or 30)).isoformat()
                        else:
                            row["expires_at"] = (now + timedelta(hours=24)).isoformat()
                            # Existing export downloads use these values in response headers.
                            if row.get("format") not in MEDIA_TYPES:
                                raise binary.invalid_archive()
                            filename = row.get("filename")
                            if (
                                not isinstance(filename, str)
                                or not 1 <= len(filename) <= 255
                                or any(char in filename for char in "\r\n/\\\0")
                            ):
                                raise binary.invalid_archive()
                    destination_pk = identity(table, row)
                    if destination_pk in ready:
                        raise binary.invalid_archive()
                    ready[destination_pk] = row, source_pk, used_fallback
                for fields in dict.fromkeys(frozenset(item[0]) for item in ready.values()):
                    items = [item[0] for item in ready.values() if item[0].keys() == fields]
                    inserted, matched = await _insert(
                        session,
                        table,
                        items,
                        assign_chat_order=name == "chat_messages" and not preview,
                    )
                    for pk, (row, source_pk, used_fallback) in ready.items():
                        if row.keys() != fields:
                            continue
                        if pk in matched:
                            mapped[source_pk] = pk
                        outcome = "new" if pk in inserted else "duplicate"
                        fingerprint.update(binary.json_bytes([name, source_pk, pk, outcome]))
                        if pk in inserted:
                            totals["new"] += 1
                            if name == "audio_objects":
                                new_audio[_uuid(row["id"])] = member_name(name, str(source_pk[0]))
                            for owner in used_fallback:
                                fallback[owner] = fallback.get(owner, 0) + 1
                            if name in MEDIA_COLUMNS and not row.get("deleted_at"):
                                member_path = member_name(name, str(source_pk[0]))
                                mime = (
                                    "audio/wav"
                                    if name == "audio_objects"
                                    else MEDIA_TYPES[row["format"]]
                                )
                                publish[member_path] = row[MEDIA_COLUMNS[name]], mime
                        else:
                            totals["duplicate"] += 1
        if len(source_ids) != manifest["counts"].get(name, 0):
            raise binary.invalid_archive()
    audio = TABLES["audio_objects"]
    new_audio_ids = list(new_audio)
    for offset in range(0, len(new_audio_ids), 1000):
        unreferenced = await session.scalars(
            audio.delete()
            .where(
                audio.c.tenant_id == tenant,
                audio.c.id.in_(new_audio_ids[offset : offset + 1000]),
                ~or_(*_audio_references(tenant)),
            )
            .returning(audio.c.id)
        )
        for audio_id in sorted(unreferenced):
            counts["audio_objects"]["new"] -= 1
            counts["audio_objects"]["skipped"] += 1
            publish.pop(new_audio[audio_id], None)
            fingerprint.update(binary.json_bytes(["unreferenced_audio", str(audio_id)]))
    if actual_media != set(media):
        raise binary.invalid_archive()
    result = {
        "counts": counts,
        "fingerprint": fingerprint.hexdigest(),
        "owners": [
            {
                "id": uid,
                "label": label,
                "fallback": fallback.get(uid, 0),
                "explicit": uid in mappings,
                "target": str(mappings[uid])
                if uid in mappings
                else uid
                if source == tenant and UUID(uid) in roles
                else str(actor),
            }
            for uid, label in declared_owners.items()
        ],
    }
    if expected is not None and result != expected:
        raise ApiError(
            "org_archive_review_changed", "داده‌های مقصد تغییر کرده‌اند. پیش‌نمایش تازه را بررسی کنید."
        )
    for member_path, info in media.items():
        if preview or member_path in publish:
            target = workspace / "media"
            await asyncio.to_thread(_read_media, archive, member_path, info, target)
            if not preview:
                key, mime = publish[member_path]
                await storage.put_path(key, target, content_type=mime)
    return result
