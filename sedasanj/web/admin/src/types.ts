export interface Kpis {
  tenants_active: number;
  calls_today: number;
  calls_failed_today: number;
  minutes_today: number;
  queue_depth: Record<string, number>;
  jobs_failed_retryable: number;
}

export interface Tenant {
  id: string;
  name: string;
  status: string;
  timezone: string;
  price_per_minute_toman: number;
  monthly_minute_quota: number | null;
  max_concurrent_jobs: number;
  audio_retention_days: number;
  max_operators: number;
  created_at: string;
}

export interface TenantUser {
  id: string;
  email: string;
  role: string;
  mobile_number: string | null;
  extension: string | null;
  created_at: string;
}

export interface TenantDetail extends Tenant {
  balance_seconds: number;
  balance_toman: number;
  calls_total: number;
  users: TenantUser[];
}

export interface TenantDatabaseStatus {
  tenant_id: string;
  tenant_name: string;
  tenant_status: string;
  database_name: string | null;
  database_status: string;
  schema_revision: string | null;
  migration_status: string | null;
  migration_phase: string | null;
  migration_error: string | null;
  cutover_at: string | null;
  rollback_until: string | null;
  backup_status: string | null;
  backup_completed_at: string | null;
  backup_checksum: string | null;
}

export interface Job {
  id: string;
  tenant_id: string;
  call_id: string;
  kind: string;
  status: string;
  attempt: number;
  run_after: string;
  error_code: string | null;
  error_detail: string | null;
}

export interface Package {
  id: string;
  name: string;
  minutes: number;
  price_toman: number;
  active: boolean;
}

export interface AuditEvent {
  id: string;
  actor_type: string;
  actor_id: string | null;
  tenant_id: string | null;
  action: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  call_id: string | null;
  kind: string;
  seconds_delta: number;
  toman_delta: number;
  created_at: string;
}

export interface PlatformSettings {
  asr_model: string;
  llm_provider: "local" | "voicesanj";
  llm_model: string;
  chat_model: string;
  prompt_version: string;
  extract_prompt: string;
  assistant_instructions: string;
  api_key_configured: boolean;
  api_key_hint: string;
  voicesanj_base_url: string;
  asr_provider: "local" | "voicesanj" | "openai_compatible";
  asr_base_url: string;
  asr_api_key_configured: boolean;
  asr_api_key_hint: string;
  local_asr_available: boolean;
  audio_preprocessing_enabled: boolean;
  audio_denoiser_model: string;
  audio_enhancement_model: string;
  analysis_concurrency: number;
  decision_model: string;
  decision_fallback_model: string;
  decision_confidence_threshold: number;
  decision_api_key_configured: boolean;
  decision_api_key_hint: string;
  embedding_base_url: string;
  embedding_model: string;
  embedding_api_key_configured: boolean;
  embedding_api_key_hint: string;
  audio_denoiser_models: AudioProcessingModel[];
  audio_enhancement_models: AudioProcessingModel[];
  mono_diarization_enabled: boolean;
  diarization_model: string;
  turn_min_seconds: number;
  turn_padding_seconds: number;
  turn_merge_gap_ms: number;
  asr_route: "native" | "ninerouter";
  analysis_route: "durable" | "ninerouter";
  chat_route: "durable" | "synchronous" | "ninerouter";
  decision_route: "native" | "ninerouter" | "typed";
  embedding_route: "native" | "ninerouter";
  ninerouter_asr_prompt: string;
  ninerouter_analysis_prompt: string;
  ninerouter_chat_prompt: string;
  ninerouter_decision_prompt: string;
  assistant_tool_mode: "auto" | "native" | "structured";
  assistant_max_tool_calls: number;
  assistant_parallel_tools: number;
  assistant_enabled_tools: string[];
  correction_enabled: boolean;
  correction_mode: "text_only" | "audio_only" | "two_stage";
  correction_audio_models: string[];
  correction_text_models: string[];
  correction_prompt: string;
  correction_strictness: "strict" | "balanced";
  correction_max_uncertain_ratio: number;
  correction_timeout_seconds: number;
  correction_max_retries: number;
  correction_failure_policy: "stop";
  asr_ai_provider: "aiservice" | "ninerouter_direct";
  analysis_provider: "aiservice" | "ninerouter_direct";
  assistant_provider: "aiservice" | "ninerouter_direct";
  correction_provider: "aiservice" | "ninerouter_direct";
  decision_provider: "aiservice" | "ninerouter_direct";
  embedding_provider: "aiservice" | "ninerouter_direct";
  ninerouter_base_url: string;
  ninerouter_api_key_configured: boolean;
  ninerouter_api_key_hint: string;
  ninerouter_connect_timeout_seconds: number;
  ninerouter_read_timeout_seconds: number;
  ninerouter_asr_model: string;
  ninerouter_analysis_model: string;
  ninerouter_assistant_model: string;
  ninerouter_correction_models: string[];
  ninerouter_decision_model: string;
  ninerouter_embedding_model: string;
  ninerouter_direct_asr_prompt: string;
  ninerouter_direct_analysis_prompt: string;
  ninerouter_direct_assistant_prompt: string;
  ninerouter_direct_correction_prompt: string;
  ninerouter_direct_decision_prompt: string;
}

export interface AssistantKnowledgeStatus {
  embedding_model: string;
  embedding_route: string;
  embedding_configured: boolean;
  ready: number;
  pending: number;
  failed: number;
  chunks: number;
  latest_error: string | null;
}

export interface AudioProcessingModel {
  id: string;
  label: string;
  description: string;
}

export interface ProviderModel {
  id: string;
  kind: string;
  display_name: string;
  description: string;
  recommended: boolean;
  available: boolean | null;
  status: string | null;
  language: string | null;
  model_id: string | null;
  architecture: string | null;
  license: string | null;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

export interface PlanVersion {
  id: string;
  plan_id: string;
  code: string;
  name: string;
  active: boolean;
  public: boolean;
  sort_order: number;
  version: number;
  status: "draft" | "published" | "retired";
  effective_at: string | null;
  monthly_price_toman: number;
  annual_price_toman: number | null;
  base_operators: number;
  intro_minutes: number;
  overage_price_per_minute_toman: number;
  assistant_tier: string;
  assistant_monthly_messages: number;
  assistant_source_limit: number;
  assistant_model: string | null;
  allows_extra_operators: boolean;
  extra_operator_monthly_toman: number | null;
  extra_operator_annual_toman: number | null;
  trial_days: number | null;
  subscription_count: number;
}

export interface SubscriptionAdmin {
  id: string;
  tenant_id: string;
  tenant_name: string;
  plan_code: string;
  plan_name: string;
  plan_version: number;
  status: string;
  billing_period: string;
  period_start: string;
  period_end: string;
  cancel_at_period_end: boolean;
  base_operators: number;
  extra_operators: number;
  assistant_monthly_messages: number;
}
