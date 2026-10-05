import TwoFactorSettings from "../components/TwoFactorSettings";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import type { AssistantKnowledgeStatus, PlatformSettings, ProviderModel } from "../types";

const LLM_KINDS = new Set(["llm", "language", "chat", "text"]);
const KIND_LABELS: Record<string, string> = {
  asr: "پیاده‌سازی صوت",
  llm: "مدل زبانی",
  decision: "تصمیم‌گیری",
  embedding: "Embedding",
};
const ASSISTANT_TOOLS: Array<[string, string]> = [
  ["search_calls", "جست‌وجوی تماس‌ها"],
  ["get_call_details", "جزئیات تماس"],
  ["search_transcripts", "جست‌وجوی متن مکالمات"],
  ["get_call_analysis", "تحلیل تماس"],
  ["get_call_analytics", "آمار تماس‌ها"],
  ["get_operator_performance", "عملکرد اپراتورها"],
  ["visualize_statistics", "نمودارهای آماری"],
];
type SettingsTab = "connection" | "models" | "assistant" | "audio" | "correction" | "prompts" | "security";
const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: "connection", label: "اتصال AISERVICE" },
  { id: "models", label: "مدل‌ها و مسیرها" },
  { id: "assistant", label: "ابزارهای دستیار" },
  { id: "audio", label: "پردازش صوت" },
  { id: "correction", label: "تصحیح متن" },
  { id: "prompts", label: "پرامپت‌ها" },
  { id: "security", label: "امنیت" },
];
function normalizeApiKey(value: string): string {
  let secret = value.trim();
  if (/^bearer\s+/i.test(secret)) {
    secret = secret.replace(/^bearer\s+/i, "").trim();
  }
  if (
    secret.length >= 2 &&
    ((secret.startsWith('"') && secret.endsWith('"')) ||
      (secret.startsWith("'") && secret.endsWith("'")))
  ) {
    secret = secret.slice(1, -1).trim();
  }
  return secret;
}

function modelOptionLabel(model: ProviderModel): string {
  const bits = [model.display_name || model.id];
  if (model.recommended) bits.push("پیشنهادی");
  if (model.available === false) bits.push("نصب‌نشده");
  else if (model.status && model.status !== "ready") bits.push(model.status);
  return bits.join(" — ");
}

function ModelSelect({
  id,
  label,
  value,
  models,
  onChange,
  required = true,
  sourceLabel = "AISERVICE",
}: {
  id: string;
  label: string;
  value: string;
  models: ProviderModel[];
  onChange: (value: string) => void;
  required?: boolean;
  sourceLabel?: string;
}) {
  const selected = models.find((model) => model.id === value);
  const missing = Boolean(value) && !selected;
  return (
    <div>
      <label className="label" htmlFor={id}>{label}</label>
      <select
        id={id}
        className="input"
        dir="ltr"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        required={required}
      >
        <option value="">انتخاب مدل از {sourceLabel}</option>
        {missing ? <option value={value}>{value} — در فهرست {sourceLabel} نیست</option> : null}
        {models.map((model) => (
          <option key={`${model.kind}:${model.id}`} value={model.id} disabled={model.available === false}>
            {modelOptionLabel(model)}
          </option>
        ))}
      </select>
      {missing ? (
        <p className="mt-1 text-xs font-medium text-rose-700">
          مدل ذخیره‌شده در فهرست فعلی {sourceLabel} وجود ندارد؛ یک مدل معتبر انتخاب کنید.
        </p>
      ) : selected?.description ? (
        <p className="mt-1 text-xs leading-5 text-slate-500">{selected.description}</p>
      ) : null}
    </div>
  );
}

function ModelPriorityList({
  id,
  label,
  value,
  models,
  onChange,
}: {
  id: string;
  label: string;
  value: string[];
  models: ProviderModel[];
  onChange: (value: string[]) => void;
}) {
  const available = models.filter((model) => !value.includes(model.id));
  function move(index: number, offset: number) {
    const target = index + offset;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }
  return (
    <div className="space-y-2">
      <label className="label" htmlFor={id}>{label}</label>
      <ol className="space-y-2">
        {value.map((modelId, index) => (
          <li key={modelId} className="flex items-center gap-2 border border-slate-200 bg-white p-2">
            <span className="w-6 text-center text-xs text-slate-500">{fmt.int(index + 1)}</span>
            <span className="min-w-0 flex-1 truncate text-sm" dir="ltr">{modelId}</span>
            <button type="button" className="btn-ghost px-2" disabled={index === 0} onClick={() => move(index, -1)} aria-label="انتقال به بالا">↑</button>
            <button type="button" className="btn-ghost px-2" disabled={index === value.length - 1} onClick={() => move(index, 1)} aria-label="انتقال به پایین">↓</button>
            <button type="button" className="btn-ghost px-2 text-rose-700" disabled={value.length === 1} onClick={() => onChange(value.filter((item) => item !== modelId))}>حذف</button>
          </li>
        ))}
      </ol>
      <select id={id} className="input" value="" onChange={(event) => event.target.value && onChange([...value, event.target.value])}>
        <option value="">افزودن مدل fallback</option>
        {available.map((model) => <option key={model.id} value={model.id}>{modelOptionLabel(model)}</option>)}
      </select>
    </div>
  );
}

export default function Settings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: SettingsTab = SETTINGS_TABS.some((tab) => tab.id === requestedTab)
    ? requestedTab as SettingsTab
    : "connection";
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [nineRouterKeyDraft, setNineRouterKeyDraft] = useState("");
  const [nineRouterModels, setNineRouterModels] = useState<ProviderModel[]>([]);
  const [testingNineRouter, setTestingNineRouter] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [testingCorrection, setTestingCorrection] = useState(false);
  const [knowledge, setKnowledge] = useState<AssistantKnowledgeStatus | null>(null);
  const [retryingKnowledge, setRetryingKnowledge] = useState(false);

  async function loadKnowledge() {
    try {
      setKnowledge(await request<AssistantKnowledgeStatus>("/v1/admin/assistant/knowledge-status"));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function loadModels() {
    setLoadingModels(true);
    setModelsError(null);
    try {
      setModels(await request<ProviderModel[]>("/v1/admin/models"));
    } catch (err) {
      setModels([]);
      setModelsError((err as Error).message);
    } finally {
      setLoadingModels(false);
    }
  }

  async function loadNineRouterModels() {
    setLoadingModels(true);
    setModelsError(null);
    try {
      const [chat, stt, embedding] = await Promise.all([
        request<ProviderModel[]>("/v1/admin/ninerouter/models?kind=chat"),
        request<ProviderModel[]>("/v1/admin/ninerouter/models?kind=stt"),
        request<ProviderModel[]>("/v1/admin/ninerouter/models?kind=embedding"),
      ]);
      setNineRouterModels([...chat, ...stt, ...embedding]);
    } catch (err) {
      setNineRouterModels([]);
      setModelsError((err as Error).message);
    } finally {
      setLoadingModels(false);
    }
  }

  async function testNineRouter() {
    setTestingNineRouter(true);
    setError(null);
    try {
      await request("/v1/admin/ninerouter/test", { method: "POST" });
      setNotice("اتصال مستقیم 9Router با موفقیت بررسی شد.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTestingNineRouter(false);
    }
  }

  useEffect(() => {
    request<PlatformSettings>("/v1/admin/settings")
      .then((data) => {
        setSettings(data);
        if (data.api_key_configured) {
          void loadModels();
        }
        if (data.ninerouter_api_key_configured) void loadNineRouterModels();
      })
      .catch((err) => setError(err.message));
  }, []);
  useEffect(() => { if (activeTab === "assistant") void loadKnowledge(); }, [activeTab]);

  const asrModels = useMemo(
    () => models.filter((model) => model.kind === "asr"),
    [models],
  );
  const llmModels = useMemo(
    () => models.filter((model) => LLM_KINDS.has(model.kind)),
    [models],
  );
  const decisionModels = useMemo(
    () => models.filter((model) => model.kind === "decision"),
    [models],
  );
  const embeddingModels = useMemo(
    () => models.filter((model) => model.kind === "embedding"),
    [models],
  );
  const nineRouterAsrModels = useMemo(() => nineRouterModels.filter((model) => model.kind === "asr"), [nineRouterModels]);
  const nineRouterLlmModels = useMemo(() => nineRouterModels.filter((model) => LLM_KINDS.has(model.kind)), [nineRouterModels]);
  const nineRouterEmbeddingModels = useMemo(() => nineRouterModels.filter((model) => model.kind === "embedding"), [nineRouterModels]);
  const modelCounts = useMemo(
    () => models.reduce<Record<string, number>>((result, model) => {
      result[model.kind] = (result[model.kind] || 0) + 1;
      return result;
    }, {}),
    [models],
  );
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setError(null);
    setNotice(null);
    const modelsNeedAiService = [
      settings.asr_ai_provider,
      settings.analysis_provider,
      settings.assistant_provider,
      settings.correction_provider,
      settings.decision_provider,
      settings.embedding_provider,
    ].includes("aiservice");
    if (
      activeTab === "models" &&
      modelsNeedAiService &&
      !settings.api_key_configured &&
      !apiKeyDraft.trim()
    ) {
      setError("ابتدا کلید API سرویس را در تب اتصال AISERVICE ذخیره کنید.");
      return;
    }
    if (activeTab === "models" && models.length) {
      const selections = [
        ["مدل ASR", settings.asr_ai_provider === "ninerouter_direct" ? settings.ninerouter_asr_model : settings.asr_model, settings.asr_ai_provider === "ninerouter_direct" ? nineRouterAsrModels : asrModels],
        ["مدل تحلیل", settings.analysis_provider === "ninerouter_direct" ? settings.ninerouter_analysis_model : settings.llm_model, settings.analysis_provider === "ninerouter_direct" ? nineRouterLlmModels : llmModels],
        ["مدل دستیار", settings.assistant_provider === "ninerouter_direct" ? settings.ninerouter_assistant_model : settings.chat_model, settings.assistant_provider === "ninerouter_direct" ? nineRouterLlmModels : llmModels],
        ["مدل تصمیم‌گیری", settings.decision_provider === "ninerouter_direct" ? settings.ninerouter_decision_model : settings.decision_model, settings.decision_provider === "ninerouter_direct" ? nineRouterLlmModels : decisionModels],
        ["مدل embedding", settings.embedding_provider === "ninerouter_direct" ? settings.ninerouter_embedding_model : settings.embedding_model, settings.embedding_provider === "ninerouter_direct" ? nineRouterEmbeddingModels : embeddingModels],
      ] as const;
      const invalid = selections.find(([, value, options]) => {
        if (!options.length) return false;
        const selected = options.find((model) => model.id === value);
        return !selected || selected.available === false;
      });
      if (invalid) {
        setError(`${invalid[0]} باید از فهرست مدل‌های آماده سرویس انتخاب‌شده انتخاب شود.`);
        return;
      }
    }
    try {
      const body: Record<string, string | boolean | number | string[]> = {};
      if (activeTab === "connection") {
        body.voicesanj_base_url = settings.voicesanj_base_url;
        if (settings.api_key_configured || apiKeyDraft.trim()) {
          body.llm_provider = settings.llm_provider;
          body.asr_provider = settings.asr_provider;
        }
        if (apiKeyDraft.trim()) {
          body.api_key = normalizeApiKey(apiKeyDraft);
        }
        body.ninerouter_base_url = settings.ninerouter_base_url;
        body.ninerouter_connect_timeout_seconds = settings.ninerouter_connect_timeout_seconds;
        body.ninerouter_read_timeout_seconds = settings.ninerouter_read_timeout_seconds;
        if (nineRouterKeyDraft.trim()) body.ninerouter_api_key = normalizeApiKey(nineRouterKeyDraft);
      } else if (activeTab === "models") {
        Object.assign(body, {
          asr_model: settings.asr_model,
          llm_model: settings.llm_model,
          chat_model: settings.chat_model,
          decision_model: settings.decision_model,
          decision_fallback_model: settings.decision_fallback_model,
          decision_confidence_threshold: settings.decision_confidence_threshold,
          asr_route: settings.asr_route,
          analysis_route: settings.analysis_route,
          chat_route: settings.chat_route,
          decision_route: settings.decision_route,
          embedding_route: settings.embedding_route,
          asr_ai_provider: settings.asr_ai_provider,
          analysis_provider: settings.analysis_provider,
          assistant_provider: settings.assistant_provider,
          decision_provider: settings.decision_provider,
          embedding_provider: settings.embedding_provider,
          ninerouter_asr_model: settings.ninerouter_asr_model,
          ninerouter_analysis_model: settings.ninerouter_analysis_model,
          ninerouter_assistant_model: settings.ninerouter_assistant_model,
          ninerouter_decision_model: settings.ninerouter_decision_model,
          ninerouter_embedding_model: settings.ninerouter_embedding_model,
          ninerouter_direct_asr_prompt: settings.ninerouter_direct_asr_prompt,
          ninerouter_direct_analysis_prompt: settings.ninerouter_direct_analysis_prompt,
          ninerouter_direct_assistant_prompt: settings.ninerouter_direct_assistant_prompt,
          ninerouter_direct_decision_prompt: settings.ninerouter_direct_decision_prompt,
        });
        if (settings.asr_route === "ninerouter") {
          body.ninerouter_asr_prompt = settings.ninerouter_asr_prompt;
        }
        if (settings.analysis_route === "ninerouter") {
          body.ninerouter_analysis_prompt = settings.ninerouter_analysis_prompt;
        }
        if (settings.chat_route === "ninerouter") {
          body.ninerouter_chat_prompt = settings.ninerouter_chat_prompt;
        }
        if (settings.decision_route === "ninerouter") {
          body.ninerouter_decision_prompt = settings.ninerouter_decision_prompt;
        }
        if (settings.embedding_model.trim()) {
          body.embedding_model = settings.embedding_model;
        }
      } else if (activeTab === "audio") {
        Object.assign(body, {
          audio_preprocessing_enabled: settings.audio_preprocessing_enabled,
          audio_denoiser_model: settings.audio_denoiser_model,
          audio_enhancement_model: settings.audio_enhancement_model,
          analysis_concurrency: settings.analysis_concurrency,
          mono_diarization_enabled: settings.mono_diarization_enabled,
          diarization_model: settings.diarization_model,
          turn_min_seconds: settings.turn_min_seconds,
          turn_padding_seconds: settings.turn_padding_seconds,
          turn_merge_gap_ms: settings.turn_merge_gap_ms,
        });
      } else if (activeTab === "assistant") {
        Object.assign(body, {
          assistant_tool_mode: settings.assistant_tool_mode,
          assistant_max_tool_calls: settings.assistant_max_tool_calls,
          assistant_parallel_tools: settings.assistant_parallel_tools,
          assistant_enabled_tools: settings.assistant_enabled_tools,
        });
      } else if (activeTab === "correction") {
        Object.assign(body, {
          correction_enabled: settings.correction_enabled,
          correction_mode: settings.correction_mode,
          correction_audio_models: settings.correction_audio_models,
          correction_text_models: settings.correction_text_models,
          correction_prompt: settings.correction_prompt,
          correction_strictness: settings.correction_strictness,
          correction_max_uncertain_ratio: settings.correction_max_uncertain_ratio,
          correction_timeout_seconds: settings.correction_timeout_seconds,
          correction_max_retries: settings.correction_max_retries,
          correction_failure_policy: settings.correction_failure_policy,
          correction_provider: settings.correction_provider,
          ninerouter_correction_models: settings.ninerouter_correction_models,
          ninerouter_direct_correction_prompt: settings.ninerouter_direct_correction_prompt,
        });
      } else if (activeTab === "prompts") {
        body.extract_prompt = settings.extract_prompt;
        body.assistant_instructions = settings.assistant_instructions;
      }
      const saved = await request<PlatformSettings>("/v1/admin/settings", {
        method: "PATCH",
        body,
      });
      setSettings(saved);
      setApiKeyDraft("");
      setNineRouterKeyDraft("");
      setNotice("ذخیره شد.");
      if (
        saved.api_key_configured &&
        (activeTab === "connection" || activeTab === "models")
      ) {
        await loadModels();
      }
      if (saved.ninerouter_api_key_configured && (activeTab === "connection" || activeTab === "models")) {
        await loadNineRouterModels();
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function testCorrection() {
    setTestingCorrection(true);
    setError(null);
    setNotice(null);
    try {
      const result = await request<{ status: string; stages: Array<{ stage: string; status: string }> }>("/v1/admin/settings/test-correction", { method: "POST" });
      const stages = result.stages.map((item) => `${item.stage}: ${item.status}`).join("، ");
      setNotice(`نتیجه آزمایش مسیر: ${result.status} — ${stages}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setTestingCorrection(false);
    }
  }

  async function retryKnowledge() {
    setRetryingKnowledge(true);
    setError(null);
    try {
      const result = await request<{ processed: number }>("/v1/admin/assistant/knowledge-retry", { method: "POST", body: { failed_only: true } });
      setNotice(`${fmt.int(result.processed)} رکورد دوباره پردازش شد.`);
      await loadKnowledge();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRetryingKnowledge(false);
    }
  }

  if (!settings) return error ? <ErrorBox message={error} /> : <Loading />;

  return (
    <div className="max-w-6xl space-y-5">
      <div className="card space-y-4">
        <div>
          <h1 className="text-lg font-bold text-slate-900">تنظیمات سامانه</h1>
          <p className="mt-1 text-sm text-slate-500">اتصال، مدل‌ها، پردازش و امنیت را از بخش مربوط مدیریت کنید.</p>
        </div>
        <div className="flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist" aria-label="بخش‌های تنظیمات">
          {SETTINGS_TABS.map((tab) => (
            <button
              key={tab.id}
              id={`settings-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`settings-panel-${tab.id}`}
              className={`shrink-0 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-[var(--primary)] text-[var(--primary)]"
                  : "border-transparent text-slate-500 hover:text-slate-900"
              }`}
              onClick={() => {
                const next = new URLSearchParams(searchParams);
                next.set("tab", tab.id);
                setSearchParams(next, { replace: true });
                setError(null);
                setNotice(null);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "security" ? (
        <div id="settings-panel-security" role="tabpanel" aria-labelledby="settings-tab-security">
          <TwoFactorSettings />
        </div>
      ) : null}
    <form
      id={activeTab === "security" ? undefined : `settings-panel-${activeTab}`}
      role="tabpanel"
      aria-labelledby={`settings-tab-${activeTab}`}
      className={`card space-y-5 ${activeTab === "security" ? "hidden" : ""}`}
      onSubmit={save}
    >
      <ErrorBox message={error} />
      {notice ? <div className="text-sm text-emerald-700">{notice}</div> : null}

      <div className={activeTab === "connection" ? "" : "hidden"}>
        <label className="label" htmlFor="llm-provider">درگاه مرکزی همه قابلیت‌های هوش مصنوعی</label>
        <select
          id="llm-provider"
          className="input"
          value={settings.llm_provider}
          disabled
          onChange={(event) => setSettings({
            ...settings,
            llm_provider: event.target.value as PlatformSettings["llm_provider"],
          })}
        >
          <option value="voicesanj">AISERVICE / VoiceSanj</option>
        </select>
        <p className="mt-1 text-xs text-slate-500">
          تمام مدل‌های برنامه فقط از طریق AISERVICE فراخوانی می‌شوند.
        </p>
      </div>

      <section className={`${activeTab === "connection" ? "" : "hidden"} space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">اتصال مستقیم 9Router</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">این اتصال هیچ درخواستی را از AISERVICE عبور نمی‌دهد و فقط برای قابلیت‌هایی استفاده می‌شود که مسیر مستقیم آن‌ها فعال شده باشد.</p>
        </div>
        <div>
          <label className="label" htmlFor="ninerouter-base-url">آدرس پایه 9Router</label>
          <input id="ninerouter-base-url" className="input" dir="ltr" type="url" value={settings.ninerouter_base_url} onChange={(event) => setSettings({ ...settings, ninerouter_base_url: event.target.value })} placeholder="https://router.example.com" />
        </div>
        <div>
          <label className="label" htmlFor="ninerouter-api-key">کلید API مستقیم 9Router</label>
          <input id="ninerouter-api-key" className="input" dir="ltr" type="password" autoComplete="off" value={nineRouterKeyDraft} onChange={(event) => setNineRouterKeyDraft(event.target.value)} placeholder={settings.ninerouter_api_key_configured ? `کلید فعلی: ${settings.ninerouter_api_key_hint || "••••"} (برای تغییر بنویسید)` : "9r_..."} />
          <p className="mt-1 text-xs text-slate-500">کلید با PLATFORM_SECRETS_KEY رمزگذاری می‌شود و مقدار کامل آن هرگز به مرورگر بازگردانده نمی‌شود.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div><label className="label">مهلت اتصال (ثانیه)</label><input className="input" type="number" min="1" max="60" value={settings.ninerouter_connect_timeout_seconds} onChange={(event) => setSettings({ ...settings, ninerouter_connect_timeout_seconds: Number(event.target.value) })} /></div>
          <div><label className="label">مهلت پاسخ (ثانیه)</label><input className="input" type="number" min="10" max="3600" value={settings.ninerouter_read_timeout_seconds} onChange={(event) => setSettings({ ...settings, ninerouter_read_timeout_seconds: Number(event.target.value) })} /></div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost" disabled={!settings.ninerouter_api_key_configured || testingNineRouter} onClick={() => void testNineRouter()}>{testingNineRouter ? "در حال آزمایش…" : "آزمایش اتصال مستقیم"}</button>
          <button type="button" className="btn-ghost" disabled={!settings.ninerouter_api_key_configured || loadingModels} onClick={() => void loadNineRouterModels()}>بازیابی مدل‌های 9Router</button>
        </div>
      </section>

      <div className={activeTab === "connection" ? "" : "hidden"}>
        <label className="label">کلید API مشترک AISERVICE</label>
        <input
          className="input"
          dir="ltr"
          type="password"
          autoComplete="off"
          placeholder={
            settings.api_key_configured
              ? `کلید فعلی: ${settings.api_key_hint || "••••"} (برای تغییر بنویسید)`
              : "کلید API AISERVICE"
          }
          value={apiKeyDraft}
          onChange={(event) => setApiKeyDraft(event.target.value)}
          required={!settings.api_key_configured}
        />
        <p className="mt-1 text-xs text-slate-500">
          {settings.api_key_configured
            ? "خالی بگذارید تا کلید فعلی حفظ شود. کلید را بدون علامت نقل‌قول وارد کنید."
            : "کلید فقط از همین صفحه ذخیره می‌شود (از فایل .env خوانده نمی‌شود)."}
        </p>
      </div>

      <section className={`${activeTab === "models" ? "" : "hidden"} space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">سرویس پیاده‌سازی صوت</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">
            ارائه‌دهنده ASR مستقل از سرویس تحلیل متن انتخاب می‌شود.
          </p>
        </div>
        <div><label className="label">مسیر اجرای ASR</label><select className="input" value={settings.asr_ai_provider} onChange={(event) => setSettings({ ...settings, asr_ai_provider: event.target.value as PlatformSettings["asr_ai_provider"] })}><option value="aiservice">AISERVICE</option><option value="ninerouter_direct">9Router مستقیم</option></select></div>
        {settings.asr_ai_provider === "ninerouter_direct" ? <><ModelSelect id="ninerouter-asr-model" label="مدل مستقیم ASR" value={settings.ninerouter_asr_model} models={nineRouterAsrModels} sourceLabel="9Router" onChange={(ninerouter_asr_model) => setSettings({ ...settings, ninerouter_asr_model })} /><div><label className="label">پرامپت مستقیم ASR</label><textarea className="input min-h-32" value={settings.ninerouter_direct_asr_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_direct_asr_prompt: event.target.value })} /></div></> : null}
        <div>
          <label className="label" htmlFor="asr-provider">درگاه اتصال</label>
          <select
            id="asr-provider"
            className="input"
            value={settings.asr_provider}
            disabled
          >
            <option value="voicesanj">AISERVICE</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="asr-base-url">آدرس پایه سرویس ASR</label>
          <input
            id="asr-base-url"
            className="input"
            dir="ltr"
            type="url"
            spellCheck={false}
            value={settings.asr_base_url}
            readOnly
            required
          />
          <p className="mt-1 text-xs text-slate-500">
            مسیر /v1/audio/transcriptions به‌صورت خودکار اضافه می‌شود.
          </p>
        </div>
        <div>
          <label className="label">مسیر ASR در AISERVICE</label>
          <select className="input" value={settings.asr_route} onChange={(event) => setSettings({ ...settings, asr_route: event.target.value as PlatformSettings["asr_route"] })}>
            <option value="native">/v1/audio/transcriptions — موتورهای نصب‌شده</option>
            <option value="ninerouter">/v1/ninerouter/audio/transcriptions — 9Router</option>
          </select>
          <p className="mt-1 text-xs text-slate-500">فایل صوتی در هر دو مسیر به‌صورت gzip به AISERVICE ارسال می‌شود.</p>
          {settings.asr_ai_provider === "aiservice" && settings.asr_route === "ninerouter" ? (
            <div className="mt-3">
              <label className="label" htmlFor="ninerouter-asr-prompt">پرامپت Speech-to-Text در 9Router</label>
              <textarea id="ninerouter-asr-prompt" className="input min-h-40 resize-y" maxLength={20000} value={settings.ninerouter_asr_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_asr_prompt: event.target.value })} />
            </div>
          ) : null}
        </div>
      </section>

      <div className={activeTab === "connection" ? "" : "hidden"}>
        <label className="label" htmlFor="voicesanj-base-url">آدرس پایه سرویس هوش مصنوعی</label>
        <input
          id="voicesanj-base-url"
          className="input"
          dir="ltr"
          type="text"
          spellCheck={false}
          placeholder="https://ai.example.com یا http://192.168.1.10:8000"
          value={settings.voicesanj_base_url}
          onChange={(event) => setSettings({ ...settings, voicesanj_base_url: event.target.value })}
          required
        />
        <p className="mt-1 text-xs text-slate-500">
          فقط دامنه یا IP، همراه با http:// یا https:// و پورت اختیاری؛ مسیرهای API را سیستم اضافه می‌کند.
        </p>
      </div>

      <div className={`${activeTab === "connection" || activeTab === "models" ? "flex" : "hidden"} items-center justify-between gap-2`}>
        <div className="text-sm text-slate-600">
          {loadingModels
            ? "در حال دریافت فهرست مدل‌ها…"
            : models.length
              ? `${fmt.int(models.length)} مدل از سرویس دریافت شد`
              : "فهرست مدل‌ها هنوز بارگذاری نشده"}
        </div>
        <button
          type="button"
          className="btn-ghost"
          disabled={loadingModels || !settings.api_key_configured}
          onClick={() => void loadModels()}
        >
          به‌روزرسانی مدل‌ها
        </button>
      </div>
      {(activeTab === "connection" || activeTab === "models") && modelsError ? <ErrorBox message={modelsError} /> : null}
      {(activeTab === "connection" || activeTab === "models") && models.length ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {Object.entries(KIND_LABELS).map(([kind, label]) => (
            <div key={kind} className="border border-slate-200 bg-white p-3">
              <div className="text-xs text-slate-500">{label}</div>
              <div className="mt-1 text-lg font-bold text-slate-900">{fmt.int(modelCounts[kind] || 0)}</div>
            </div>
          ))}
        </div>
      ) : null}

      <section className={`${activeTab === "assistant" ? "" : "hidden"} space-y-5 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">عامل ابزارمحور دستیار</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">مدل فقط ابزارهای خواندنی و محدود را انتخاب می‌کند؛ کنترل tenant و سطح دسترسی داخل سرور اعمال می‌شود.</p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <div><label className="label">حالت فراخوانی ابزار</label><select className="input" value={settings.assistant_tool_mode} onChange={(event) => setSettings({ ...settings, assistant_tool_mode: event.target.value as PlatformSettings["assistant_tool_mode"] })}><option value="auto">خودکار</option><option value="native">Native</option><option value="structured">Structured JSON</option></select></div>
          <div><label className="label">حداکثر ابزار در هر پیام</label><input className="input" type="number" min="1" max="4" value={settings.assistant_max_tool_calls} onChange={(event) => setSettings({ ...settings, assistant_max_tool_calls: Number(event.target.value) })} /></div>
          <div><label className="label">حداکثر اجرای هم‌زمان</label><input className="input" type="number" min="1" max="2" value={settings.assistant_parallel_tools} onChange={(event) => setSettings({ ...settings, assistant_parallel_tools: Number(event.target.value) })} /></div>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {ASSISTANT_TOOLS.map(([id, label]) => <ToggleSwitch key={id} checked={settings.assistant_enabled_tools.includes(id)} onChange={(checked) => setSettings({ ...settings, assistant_enabled_tools: checked ? [...settings.assistant_enabled_tools, id] : settings.assistant_enabled_tools.filter((item) => item !== id) })} label={label} />)}
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          <div className="border border-slate-200 bg-white p-3"><span className="text-xs text-slate-500">آماده</span><strong className="mt-1 block text-lg">{fmt.int(knowledge?.ready || 0)}</strong></div>
          <div className="border border-slate-200 bg-white p-3"><span className="text-xs text-slate-500">در انتظار</span><strong className="mt-1 block text-lg">{fmt.int(knowledge?.pending || 0)}</strong></div>
          <div className="border border-slate-200 bg-white p-3"><span className="text-xs text-slate-500">ناموفق</span><strong className="mt-1 block text-lg text-rose-700">{fmt.int(knowledge?.failed || 0)}</strong></div>
          <div className="border border-slate-200 bg-white p-3"><span className="text-xs text-slate-500">قطعه متن</span><strong className="mt-1 block text-lg">{fmt.int(knowledge?.chunks || 0)}</strong></div>
        </div>
        {knowledge?.latest_error ? <p className="border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800">{knowledge.latest_error}</p> : null}
        <button type="button" className="btn-ghost" disabled={retryingKnowledge || !knowledge?.failed} onClick={() => void retryKnowledge()}>{retryingKnowledge ? "در حال تلاش مجدد…" : "تلاش مجدد برای ایندکس‌های ناموفق"}</button>
      </section>

      <section className={`${activeTab === "audio" ? "" : "hidden"} space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-900">آماده‌سازی صوت پیش از تحلیل</h2>
            <p className="mt-1 text-xs leading-6 text-slate-500">
              ابتدا هر کانال صوتی حذف نویز و بهبود داده می‌شود؛ سپس همان WAV نهایی با قرارداد
              رسمی سرویس برای مدل ASR ارسال می‌گردد.
            </p>
          </div>
          <ToggleSwitch
            className="shrink-0"
            checked={settings.audio_preprocessing_enabled}
            onChange={(checked) =>
              setSettings({ ...settings, audio_preprocessing_enabled: checked })
            }
            label="فعال"
            labelClassName="text-sm font-medium"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">مدل حذف نویز</label>
            <select
              className="input"
              dir="ltr"
              disabled={!settings.audio_preprocessing_enabled}
              value={settings.audio_denoiser_model}
              onChange={(event) =>
                setSettings({ ...settings, audio_denoiser_model: event.target.value })
              }
            >
              {settings.audio_denoiser_models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {settings.audio_denoiser_models.find(
                (model) => model.id === settings.audio_denoiser_model,
              )?.description ?? ""}
            </p>
          </div>

          <div>
            <label className="label">مدل بهبود کیفیت</label>
            <select
              className="input"
              dir="ltr"
              disabled={!settings.audio_preprocessing_enabled}
              value={settings.audio_enhancement_model}
              onChange={(event) =>
                setSettings({ ...settings, audio_enhancement_model: event.target.value })
              }
            >
              {settings.audio_enhancement_models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {settings.audio_enhancement_models.find(
                (model) => model.id === settings.audio_enhancement_model,
              )?.description ?? ""}
            </p>
          </div>
        </div>
        <div className="border-t border-slate-200 pt-4">
          <div className="flex items-start justify-between gap-4">
            <div><h3 className="font-bold text-slate-900">تفکیک نوبت‌ها</h3><p className="mt-1 text-xs leading-6 text-slate-500">برای مدل‌های بدون زمان‌بندی از VAD و برای صوت تک‌کاناله از تفکیک دو گوینده استفاده می‌شود.</p></div>
            <ToggleSwitch checked={settings.mono_diarization_enabled} onChange={(mono_diarization_enabled) => setSettings({ ...settings, mono_diarization_enabled })} label="تفکیک mono" />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-4">
            <div><label className="label">مدل تفکیک گوینده</label><input className="input" dir="ltr" value={settings.diarization_model} onChange={(event) => setSettings({ ...settings, diarization_model: event.target.value })} /></div>
            <div><label className="label">حداقل نوبت (ثانیه)</label><input className="input" type="number" min="0.1" max="3" step="0.1" value={settings.turn_min_seconds} onChange={(event) => setSettings({ ...settings, turn_min_seconds: Number(event.target.value) })} /></div>
            <div><label className="label">حاشیه نوبت (ثانیه)</label><input className="input" type="number" min="0" max="1" step="0.05" value={settings.turn_padding_seconds} onChange={(event) => setSettings({ ...settings, turn_padding_seconds: Number(event.target.value) })} /></div>
            <div><label className="label">فاصله ادغام (میلی‌ثانیه)</label><input className="input" type="number" min="0" max="5000" step="100" value={settings.turn_merge_gap_ms} onChange={(event) => setSettings({ ...settings, turn_merge_gap_ms: Number(event.target.value) })} /></div>
          </div>
        </div>
      </section>

      <section className={`${activeTab === "correction" ? "" : "hidden"} space-y-5 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-bold text-slate-900">تصحیح هوشمند و نسخه نهایی متن</h2>
            <p className="mt-1 text-xs leading-6 text-slate-500">ارائه‌دهنده تصحیح مستقل است و هر نسخه با مسیر و مدل زمان ایجاد خود ادامه پیدا می‌کند.</p>
          </div>
          <ToggleSwitch checked={settings.correction_enabled} onChange={(correction_enabled) => setSettings({ ...settings, correction_enabled })} label="فعال" labelClassName="text-sm font-medium" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label" htmlFor="correction-mode">حالت اجرا</label>
            <select id="correction-mode" className="input" value={settings.correction_mode} onChange={(event) => setSettings({ ...settings, correction_mode: event.target.value as PlatformSettings["correction_mode"] })}>
              <option value="two_stage">دو مرحله‌ای دقیق</option>
              <option value="text_only">فقط تصحیح متن</option>
              <option value="audio_only">فقط خروجی مدل صوتی</option>
            </select>
          </div>
          <div>
            <label className="label" htmlFor="correction-strictness">سطح محافظه‌کاری</label>
            <select id="correction-strictness" className="input" value={settings.correction_strictness} onChange={(event) => setSettings({ ...settings, correction_strictness: event.target.value as PlatformSettings["correction_strictness"] })}>
              <option value="strict">سخت‌گیرانه</option>
              <option value="balanced">متعادل</option>
            </select>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="correction-provider">مسیر تصحیح متن</label>
          <select id="correction-provider" className="input" value={settings.correction_provider} onChange={(event) => setSettings({ ...settings, correction_provider: event.target.value as PlatformSettings["correction_provider"] })}>
            <option value="aiservice">AISERVICE</option>
            <option value="ninerouter_direct">9Router مستقیم</option>
          </select>
        </div>
        {settings.correction_provider === "ninerouter_direct" ? (
          <>
            <ModelPriorityList id="ninerouter-correction-models" label="مدل‌های مستقیم تصحیح به‌ترتیب اولویت" value={settings.ninerouter_correction_models} models={nineRouterLlmModels} onChange={(ninerouter_correction_models) => setSettings({ ...settings, ninerouter_correction_models })} />
            <div>
              <label className="label" htmlFor="ninerouter-direct-correction-prompt">پرامپت مستقیم تصحیح</label>
              <textarea id="ninerouter-direct-correction-prompt" className="input min-h-48 resize-y" value={settings.ninerouter_direct_correction_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_direct_correction_prompt: event.target.value })} />
            </div>
          </>
        ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <ModelPriorityList id="correction-audio-models" label="مدل‌های صوتی به‌ترتیب اولویت" value={settings.correction_audio_models} models={asrModels} onChange={(correction_audio_models) => setSettings({ ...settings, correction_audio_models })} />
          <ModelPriorityList id="correction-text-models" label="مدل‌های متنی به‌ترتیب اولویت" value={settings.correction_text_models} models={llmModels} onChange={(correction_text_models) => setSettings({ ...settings, correction_text_models })} />
        </div>
        )}
        <div>
          <label className="label" htmlFor="correction-prompt">پرامپت تصحیح</label>
          <textarea id="correction-prompt" className="input min-h-48 resize-y" value={settings.correction_prompt} onChange={(event) => setSettings({ ...settings, correction_prompt: event.target.value })} required />
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          <div><label className="label">آستانه هشدار موارد مشکوک</label><input className="input" type="number" min="0" max="1" step="0.01" value={settings.correction_max_uncertain_ratio} onChange={(event) => setSettings({ ...settings, correction_max_uncertain_ratio: Number(event.target.value) })} /></div>
          <div><label className="label">مهلت کل پردازش (ثانیه)</label><input className="input" type="number" min="60" max="3600" value={settings.correction_timeout_seconds} onChange={(event) => setSettings({ ...settings, correction_timeout_seconds: Number(event.target.value) })} /></div>
          <div><label className="label">تعداد تلاش</label><input className="input" type="number" min="1" max="5" value={settings.correction_max_retries} onChange={(event) => setSettings({ ...settings, correction_max_retries: Number(event.target.value) })} /></div>
        </div>
        <div>
          <label className="label">رفتار هنگام شکست همه مدل‌ها</label>
          <select className="input" value={settings.correction_failure_policy} disabled><option value="stop">توقف تحلیل و نیاز به بررسی؛ بدون fallback خام</option></select>
        </div>
        <button type="button" className="btn-ghost" disabled={testingCorrection} onClick={() => void testCorrection()}>{testingCorrection ? "در حال آزمایش submit، provider و validation…" : "آزمایش واقعی مسیر تصحیح"}</button>
      </section>

      <div className={activeTab === "audio" ? "" : "hidden"}>
        <label className="label">تعداد تحلیل هم‌زمان</label>
        <input
          className="input"
          type="text"
          inputMode="numeric"
          pattern="[0-9۰-۹]+"
          value={fmt.digits(settings.analysis_concurrency)}
          onChange={(event) => {
            const value = Number(fmt.latinDigits(event.target.value));
            if (Number.isInteger(value) && value >= 1 && value <= 3) {
              setSettings({ ...settings, analysis_concurrency: value });
            }
          }}
        />
        <p className="mt-1 text-xs text-slate-500">
          فقط ۱ تا ۳ مجاز است. هر ظرفیت تا پایان همه مراحل تحلیل همان تماس محفوظ می‌ماند؛
          تماس بعدی به‌ترتیب در صف می‌ماند تا ظرفیت آزاد شود.
        </p>
      </div>

      <div className={activeTab === "models" ? "" : "hidden"}>
        <label className="label">مسیر تحلیل مکالمات</label><select className="input mb-2" value={settings.analysis_provider} onChange={(event) => setSettings({ ...settings, analysis_provider: event.target.value as PlatformSettings["analysis_provider"] })}><option value="aiservice">AISERVICE</option><option value="ninerouter_direct">9Router مستقیم</option></select>
        <ModelSelect
          id="asr-model"
          label="مدل پیاده‌سازی صوت (ASR)"
          value={settings.asr_model}
          models={asrModels}
          onChange={(asr_model) => setSettings({ ...settings, asr_model })}
        />
      </div>

      <div className={activeTab === "models" ? "" : "hidden"}>
        <ModelSelect
          id="analysis-model"
          label="مدل تحلیل مکالمات"
          value={settings.analysis_provider === "ninerouter_direct" ? settings.ninerouter_analysis_model : settings.llm_model}
          models={settings.analysis_provider === "ninerouter_direct" ? nineRouterLlmModels : llmModels}
          sourceLabel={settings.analysis_provider === "ninerouter_direct" ? "9Router" : "AISERVICE"}
          onChange={(value) => setSettings(settings.analysis_provider === "ninerouter_direct" ? { ...settings, ninerouter_analysis_model: value } : { ...settings, llm_model: value })}
        />
        <select className="input mt-2" disabled={settings.analysis_provider === "ninerouter_direct"} value={settings.analysis_route} onChange={(event) => setSettings({ ...settings, analysis_route: event.target.value as PlatformSettings["analysis_route"] })}>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/chat/completions — 9Router از AISERVICE</option>
        </select>
        {settings.analysis_provider === "aiservice" && settings.analysis_route === "ninerouter" ? (
          <div className="mt-3">
            <label className="label" htmlFor="ninerouter-analysis-prompt">دستور تکمیلی تحلیل در 9Router</label>
            <textarea id="ninerouter-analysis-prompt" className="input min-h-40 resize-y" maxLength={20000} value={settings.ninerouter_analysis_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_analysis_prompt: event.target.value })} />
          </div>
        ) : null}
        {settings.analysis_provider === "ninerouter_direct" ? <div className="mt-3"><label className="label">پرامپت مستقیم تحلیل</label><textarea className="input min-h-40" value={settings.ninerouter_direct_analysis_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_direct_analysis_prompt: event.target.value })} /></div> : null}
      </div>

      <div className={activeTab === "models" ? "" : "hidden"}>
        <label className="label">مسیر دستیار سازمانی</label><select className="input mb-2" value={settings.assistant_provider} onChange={(event) => setSettings({ ...settings, assistant_provider: event.target.value as PlatformSettings["assistant_provider"] })}><option value="aiservice">AISERVICE</option><option value="ninerouter_direct">9Router مستقیم</option></select>
        <ModelSelect
          id="assistant-model"
          label="مدل دستیار سازمانی"
          value={settings.assistant_provider === "ninerouter_direct" ? settings.ninerouter_assistant_model : settings.chat_model}
          models={settings.assistant_provider === "ninerouter_direct" ? nineRouterLlmModels : llmModels}
          sourceLabel={settings.assistant_provider === "ninerouter_direct" ? "9Router" : "AISERVICE"}
          onChange={(value) => setSettings(settings.assistant_provider === "ninerouter_direct" ? { ...settings, ninerouter_assistant_model: value } : { ...settings, chat_model: value })}
        />
        <select className="input mt-2" disabled={settings.assistant_provider === "ninerouter_direct"} value={settings.chat_route} onChange={(event) => setSettings({ ...settings, chat_route: event.target.value as PlatformSettings["chat_route"] })}>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
          <option value="synchronous">/v1/chat/completions — پاسخ مستقیم AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/chat/completions — 9Router از AISERVICE</option>
        </select>
        {settings.assistant_provider === "aiservice" && settings.chat_route === "ninerouter" ? (
          <div className="mt-3">
            <label className="label" htmlFor="ninerouter-chat-prompt">دستور تکمیلی دستیار در 9Router</label>
            <textarea id="ninerouter-chat-prompt" className="input min-h-40 resize-y" maxLength={20000} value={settings.ninerouter_chat_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_chat_prompt: event.target.value })} />
          </div>
        ) : null}
        {settings.assistant_provider === "ninerouter_direct" ? <div className="mt-3"><label className="label">پرامپت مستقیم دستیار</label><textarea className="input min-h-40" value={settings.ninerouter_direct_assistant_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_direct_assistant_prompt: event.target.value })} /></div> : null}
      </div>

      <section className={`${activeTab === "models" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">تصمیم‌گیری محلی AISERVICE</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">مدل اصلی و fallback را از مدل‌های واقعاً قابل دسترس AISERVICE انتخاب کنید.</p>
        </div>
        <div><label className="label">مسیر تصمیم‌گیری</label><select className="input" value={settings.decision_provider} onChange={(event) => setSettings({ ...settings, decision_provider: event.target.value as PlatformSettings["decision_provider"] })}><option value="aiservice">AISERVICE typed decision</option><option value="ninerouter_direct">9Router مستقیم با JSON adapter</option></select></div>
        {settings.decision_provider === "ninerouter_direct" ? <ModelSelect id="ninerouter-decision-model" label="مدل مستقیم تصمیم‌گیری" value={settings.ninerouter_decision_model} models={nineRouterLlmModels} sourceLabel="9Router" onChange={(ninerouter_decision_model) => setSettings({ ...settings, ninerouter_decision_model })} /> : null}
        <div className="grid gap-3 md:grid-cols-2">
          <ModelSelect id="decision-model" label="مدل اصلی" value={settings.decision_model} models={decisionModels} onChange={(decision_model) => setSettings({ ...settings, decision_model })} />
          <ModelSelect id="decision-fallback-model" label="مدل fallback" value={settings.decision_fallback_model} models={decisionModels} onChange={(decision_fallback_model) => setSettings({ ...settings, decision_fallback_model })} />
        </div>
        <div>
          <label className="label" htmlFor="decision-threshold">حداقل اطمینان برای استفاده از مدل اصلی</label>
          <input id="decision-threshold" className="input" type="number" min="0" max="1" step="0.01" value={settings.decision_confidence_threshold} onChange={(event) => setSettings({ ...settings, decision_confidence_threshold: Number(event.target.value) })} />
        </div>
        <select className="input" disabled={settings.decision_provider === "ninerouter_direct"} value={settings.decision_route === "typed" ? "native" : settings.decision_route} onChange={(event) => setSettings({ ...settings, decision_route: event.target.value as PlatformSettings["decision_route"] })}>
          <option value="native">/v1/decisions — موتور تصمیم‌گیری محلی AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/decisions — تصمیم‌گیری 9Router</option>
        </select>
        {settings.decision_provider === "aiservice" && settings.decision_route === "ninerouter" ? (
          <div>
            <label className="label" htmlFor="ninerouter-decision-prompt">دستور تکمیلی تصمیم‌گیری در 9Router</label>
            <textarea id="ninerouter-decision-prompt" className="input min-h-40 resize-y" maxLength={20000} value={settings.ninerouter_decision_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_decision_prompt: event.target.value })} />
          </div>
        ) : null}
        {settings.decision_provider === "ninerouter_direct" ? <div><label className="label">پرامپت مستقیم تصمیم‌گیری</label><textarea className="input min-h-40" value={settings.ninerouter_direct_decision_prompt} onChange={(event) => setSettings({ ...settings, ninerouter_direct_decision_prompt: event.target.value })} /></div> : null}
      </section>

      <section className={`${activeTab === "models" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">Embedding و بازیابی برداری</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">فقط مدل‌های embedding اعلام‌شده توسط AISERVICE نمایش داده می‌شوند؛ شناسه فرضی یا نصب‌نشده ذخیره نمی‌شود.</p>
        </div>
        <div><label className="label">مسیر Embedding</label><select className="input" value={settings.embedding_provider} onChange={(event) => setSettings({ ...settings, embedding_provider: event.target.value as PlatformSettings["embedding_provider"] })}><option value="aiservice">AISERVICE</option><option value="ninerouter_direct">9Router مستقیم</option></select></div>
        <ModelSelect id="embedding-model" label="مدل Embedding" value={settings.embedding_provider === "ninerouter_direct" ? settings.ninerouter_embedding_model : settings.embedding_model} models={settings.embedding_provider === "ninerouter_direct" ? nineRouterEmbeddingModels : embeddingModels} sourceLabel={settings.embedding_provider === "ninerouter_direct" ? "9Router" : "AISERVICE"} onChange={(value) => setSettings(settings.embedding_provider === "ninerouter_direct" ? { ...settings, ninerouter_embedding_model: value } : { ...settings, embedding_model: value })} />
        <select className="input" disabled={settings.embedding_provider === "ninerouter_direct"} value={settings.embedding_route} onChange={(event) => setSettings({ ...settings, embedding_route: event.target.value as PlatformSettings["embedding_route"] })}>
          <option value="native">/v1/embeddings — مدل نصب‌شده محلی AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/embeddings — 9Router از AISERVICE</option>
        </select>
      </section>


      <section className={`${activeTab === "prompts" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">پرامپت اصلی تحلیل</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">
            پرامپت فعال {settings.prompt_version} برای تحلیل‌های جدید. هر تحلیل با نسخه ذخیره‌شده خودش اجرا می‌شود.
          </p>
        </div>
        <textarea
          className="input min-h-96 resize-y font-mono text-sm leading-6"
          dir="rtl"
          spellCheck={false}
          value={settings.extract_prompt}
          onChange={(event) => setSettings({ ...settings, extract_prompt: event.target.value })}
          required
        />
      </section>
      <section className={`${activeTab === "prompts" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">دستورها و اطلاعات دستیار</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">
            این متن در تمام پیام‌های دستیار همراه با اطلاعات زمینهٔ گفتگو ارسال می‌شود.
          </p>
        </div>
        <textarea
          className="input min-h-56 resize-y font-mono text-sm leading-6"
          dir="rtl"
          spellCheck={false}
          value={settings.assistant_instructions}
          onChange={(event) => setSettings({ ...settings, assistant_instructions: event.target.value })}
        />
      </section>
      <button className="btn">
        ذخیره {SETTINGS_TABS.find((tab) => tab.id === activeTab)?.label}
      </button>
    </form>
    </div>
  );
}
