import type { AssistantChart } from "../types";

export type ReportInput = { name: string; instructions: string; enabled: boolean; schedule_mode: "interval" | "fixed"; interval_hours: number | null; fixed_hours: number[]; max_retries: number; retry_base_minutes: number };
export type Report = ReportInput & { id: string; next_run_at: string | null; archived_at: string | null };
export type Run = { id: string; report_id: string; name: string; title?: string | null; instructions: string; trigger: string; status: string; from_date: string; to_date: string; timezone: string; content: string | null; charts?: AssistantChart[]; error_detail: string | null; created_at: string; sources: {call_id: string}[]; model: string | null; attempt_count: number; max_retries: number; next_attempt_at: string | null; coverage: Record<string, unknown> };
export type RunSummary = Pick<Run, "id" | "report_id" | "name" | "title" | "trigger" | "status" | "from_date" | "to_date" | "created_at" | "error_detail" | "attempt_count" | "max_retries" | "next_attempt_at" | "coverage">;
