export type Sentiment = "angry" | "sad" | "neutral" | "satisfied" | "happy";
export type SentimentTrajectory = "improved" | "worsened" | "stable";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface CallSummary {
  id: string;
  asterisk_uniqueid: string;
  caller_number: string | null;
  dialed_number: string | null;
  direction: string | null;
  agent_extension: string | null;
  started_at: string;
  ended_at: string;
  updated_at: string;
  duration_ms: number;
  billed_seconds: number | null;
  status: string;
  error_code: string | null;
  progress_pct: number;
  progress_detail: string | null;
  processing: boolean;
  recovery_pending: boolean;
  summary: string | null;
  sentiment: Sentiment | null;
  sentiment_trajectory: SentimentTrajectory | null;
  intent: string | null;
}

export interface CallPage {
  items: CallSummary[];
  next_cursor: string | null;
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

export interface Utterance {
  channel: number;
  t_start_ms: number;
  t_end_ms: number;
  text: string;
  source_text?: string | null;
  uncertain?: boolean;
}

export interface CorrectionStatus {
  id: string;
  status: "queued" | "running" | "validating" | "succeeded" | "failed";
  trigger: "automatic" | "manual";
  mode: "text_only" | "audio_only" | "two_stage";
  audio_models: string[];
  text_models: string[];
  provider_model: string | null;
  error_code: string | null;
  error_detail: string | null;
  uncertain_items: Array<Record<string, unknown>>;
  queued_at: string;
  started_at: string | null;
  provider_submitted_at: string | null;
  completed_at: string | null;
}

export interface SentimentPoint {
  label: Sentiment;
  score: number;
}

export interface PartySentiment {
  start: SentimentPoint;
  end: SentimentPoint;
  overall: SentimentPoint;
  delta: number;
  trajectory: SentimentTrajectory;
  timeline: SentimentWindow[];
}

export interface SentimentWindow {
  t_start_ms: number;
  t_end_ms: number;
  label: Sentiment;
  score: number;
  valence: number;
}

export interface DualPartySentiment {
  caller: PartySentiment;
  agent: PartySentiment | null;
}

export interface SentimentProfile {
  text: DualPartySentiment | null;
  voice: DualPartySentiment | null;
  voice_model: string | null;
}

export interface Insights {
  summary: string | null;
  keywords: string[] | null;
  sentiment: Sentiment | null;
  sentiment_score: number | null;
  sentiment_profile: SentimentProfile | null;
  intent: string | null;
  topics: string[] | null;
  ner: Record<string, string[]> | null;
  action_items: string[] | null;
}

export interface CallDetail extends CallSummary {
  audio_available: boolean;
  transcript: string | null;
  corrected_transcript: string | null;
  corrected_transcript_at: string | null;
  asr_model: string | null;
  utterances: Utterance[];
  raw_utterances: Utterance[];
  speaker_labels: Record<number, string>;
  correction: CorrectionStatus | null;
  insights: Insights | null;
  sales: {
    funnel_stage: string;
    outcome: string;
    certainty: string;
    confidence: number;
    product: string | null;
    objections: string[];
    win_loss_reason: string | null;
    next_action: string | null;
    next_action_due_at: string | null;
    evidence: Array<{ text: string; t_start_ms: number | null; t_end_ms: number | null }>;
  } | null;
  tasks: FollowUpTask[];
  analysis_run_id: string | null;
  prompt_version: string | null;
  llm_model: string | null;
  error_detail: string | null;
  processing_events: ProcessingEvent[];
}

export interface ScoreCriterion {
  title: string;
  description: string;
  weight: number;
}

export interface ScoreRubric {
  id: string;
  version: number;
  criteria: ScoreCriterion[];
  active: boolean;
  created_at: string;
}

export interface OperatorScore {
  id: string;
  call_id: string;
  operator_id: string | null;
  operator_label: string;
  status: string;
  total_score: number | null;
  criteria_scores: Array<{ title: string; score: number; evidence?: string; t_start_ms?: number }> | null;
  created_at: string;
  completed_at: string | null;
}

export interface OperatorScoreReport {
  from_date: string | null;
  to_date: string | null;
  ranking_visible: boolean;
  items: Array<{ operator_id: string | null; operator_label: string; average_score: number | null; scored_calls: number; rank: number | null }>;
  total: number;
}

export interface ChatConversation {
  id: string;
  call_id: string | null;
  title: string | null;
  archived_at: string | null;
  pinned_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  model: string | null;
  sources: AssistantCallSource[] | null;
  tool_runs: AssistantToolRun[];
  created_at: string;
}

export interface AssistantCallSource {
  call_id: string;
  started_at: string | null;
  ended_at?: string | null;
  caller_number?: string | null;
  dialed_number?: string | null;
  direction?: string | null;
  agent_extension?: string | null;
  duration_ms?: number | null;
  status?: string | null;
  summary: string | null;
  intent?: string | null;
  sentiment?: Sentiment | null;
}

export interface AssistantToolRun {
  tool_call_id: string;
  name: string;
  title: string;
  status: "running" | "succeeded" | "failed";
  duration_ms: number | null;
  summary: string | null;
  error_code: string | null;
  charts?: AssistantChart[];
}

export interface AssistantChart {
  id: string;
  title: string;
  type: "bar" | "horizontal_bar" | "line" | "area" | "pie" | "donut" | "radar" | "radial_bar" | "scatter" | "composed" | "treemap" | "funnel";
  size: "half" | "full";
  value_label: string;
  secondary_value_label?: string | null;
  data: Array<{ label: string; value: number; secondary_value?: number }>;
}

export interface ProcessingEvent {
  id: string;
  kind: "pipeline" | "asr" | "emotion" | "correction" | "llm" | "notify";
  level: "info" | "success" | "warning" | "error";
  status: string | null;
  progress_pct: number | null;
  message: string;
  error_code: string | null;
  error_detail: string | null;
  step_key: string | null;
  created_at: string;
}

export interface AnalyticsBucket {
  key: string;
  count: number;
}

export interface AnalyticsTrendPoint {
  date: string;
  angry: number;
  sad: number;
  neutral: number;
  satisfied: number;
  happy: number;
}

export interface AnalyticsSummary {
  from_date: string;
  to_date: string;
  total_calls: number;
  total_minutes: number;
  intents: AnalyticsBucket[];
  sentiments: AnalyticsBucket[];
  caller_trajectories: AnalyticsBucket[];
  agent_sentiments: AnalyticsBucket[];
  agent_trajectories: AnalyticsBucket[];
  trend: AnalyticsTrendPoint[];
}

export interface RateMetric {
  value: number | null;
  numerator: number;
  denominator: number;
  previous_value?: number | null;
  change?: number | null;
}

export interface KpiDashboard {
  from_date: string;
  to_date: string;
  role: string;
  settings: {
    minimum_sample_size: number;
    operator_team_comparison_visible: boolean;
  };
  cards: {
    total_calls: number;
    effective_calls: number;
    opportunities: number;
    explicit_wins: number;
    probable_opportunities: number;
    probable_opportunity_rate: RateMetric;
    unknown_outcomes: number;
    ai_win_rate: RateMetric;
    crm_conversion_rate: RateMetric;
    outcome_coverage: RateMetric;
    revenue: number;
    pipeline_value: number;
    currency: string | null;
    quality_score: number | null;
    follow_up_sla_rate: RateMetric;
    sentiment_improvement: RateMetric;
    hot_unassigned: number;
    goal_achievement: Array<{ metric: string; actual: number | null; target: number; achievement: number | null }>;
  };
  funnel: Array<{ key: string; count: number; pass_rate: number | null; drop_rate: number | null; previous_count?: number; change_percent?: number | null }>;
  breakdowns: {
    topics: Array<[string, number]>;
    objections: Array<[string, number]>;
    products: Array<[string, number]>;
    win_loss_reasons: Array<[string, number]>;
    campaigns: Array<{ key: string; calls: number; opportunities: number; wins: number; conversion: RateMetric }>;
    campaigns_total: number;
  };
  operators: Array<{
    operator_id: string;
    operator_label: string;
    calls: number;
    wins: number;
    opportunities: number;
    conversion: RateMetric;
    quality_score: number | null;
    sample_sufficient: boolean;
    agent_talk_ratio: number | null;
  }>;
  operators_total: number;
  actions: Array<{ type: string; severity: string; call_id: string | null; title: string; due_at: string | null }>;
  coaching: {
    strengths: Array<{ title: string; average: number; call_id: string; evidence: string | null }>;
    improvements: Array<{ title: string; average: number; call_id: string; evidence: string | null }>;
  };
  filters: {
    directions: string[];
    campaigns: string[];
    sources: string[];
    intents: string[];
    certainties: string[];
    teams: Array<{ id: string; name: string }>;
    operators: Array<{ id: string; name: string }>;
  };
}

export interface Balance {
  seconds: number;
  minutes: number;
  toman: number;
  price_per_minute_toman: number;
  expiring_seconds: number;
  purchased_seconds: number;
  next_expiration_at: string | null;
}

export interface PublicPlan {
  code: "demo" | "bronze" | "silver" | "gold";
  name: string;
  version: number;
  monthly_price_toman: number;
  annual_price_toman: number | null;
  base_operators: number;
  intro_minutes: number;
  overage_price_per_minute_toman: number;
  assistant_tier: string;
  assistant_monthly_messages: number;
  assistant_source_limit: number;
  allows_extra_operators: boolean;
  extra_operator_monthly_toman: number | null;
  extra_operator_annual_toman: number | null;
  trial_days: number | null;
}

export interface LedgerEntry {
  id: string;
  call_id: string | null;
  kind: string;
  seconds_delta: number;
  toman_delta: number;
  created_at: string;
}

export interface Package {
  id: string;
  name: string;
  minutes: number;
  price_toman: number;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  label: string | null;
  archive_format: "wav" | "gzip" | "zip";
  archive_password_configured: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  secret: string;
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
}

export interface WebhookCreated extends Webhook {
  secret: string;
}

export interface User {
  id: string;
  email: string;
  role: string;
  mobile_number: string | null;
  extension: string | null;
  created_at: string;
}

export interface AccountInfo {
  tenant: {
    id: string;
    name: string;
    max_operators: number;
  };
  user: User;
}

export type TaskStatus = "open" | "done";
export type TaskPriority = "low" | "normal" | "high";

export interface FollowUpTask {
  id: string;
  call_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority | null;
  due_date: string | null;
  source_phone: string | null;
  caller_number: string | null;
  dialed_number: string | null;
  agent_extension: string | null;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
}

export interface TaskDay {
  date: string;
  items: FollowUpTask[];
}

export interface TaskBoard {
  today: FollowUpTask[];
  upcoming: TaskDay[];
  completed: FollowUpTask[];
  open_count: number;
  today_count: number;
  upcoming_count: number;
  completed_count: number;
}
