import TwoFactorSettings from "../components/TwoFactorSettings";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useMemo, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import type { PlatformSettings, ProviderModel } from "../types";

const LLM_KINDS = new Set(["llm", "language", "chat", "text"]);
const KIND_LABELS: Record<string, string> = {
  asr: "پیاده‌سازی صوت",
  llm: "مدل زبانی",
  decision: "تصمیم‌گیری",
  embedding: "Embedding",
};
type SettingsTab = "connection" | "models" | "audio" | "prompts" | "security";
const SETTINGS_TABS: Array<{ id: SettingsTab; label: string }> = [
  { id: "connection", label: "اتصال AISERVICE" },
  { id: "models", label: "مدل‌ها و مسیرها" },
  { id: "audio", label: "پردازش صوت" },
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
}: {
  id: string;
  label: string;
  value: string;
  models: ProviderModel[];
  onChange: (value: string) => void;
  required?: boolean;
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
        <option value="">انتخاب مدل از AISERVICE</option>
        {missing ? <option value={value}>{value} — در فهرست AISERVICE نیست</option> : null}
        {models.map((model) => (
          <option key={`${model.kind}:${model.id}`} value={model.id} disabled={model.available === false}>
            {modelOptionLabel(model)}
          </option>
        ))}
      </select>
      {missing ? (
        <p className="mt-1 text-xs font-medium text-rose-700">
          مدل ذخیره‌شده در فهرست فعلی AISERVICE وجود ندارد؛ یک مدل معتبر انتخاب کنید.
        </p>
      ) : selected?.description ? (
        <p className="mt-1 text-xs leading-5 text-slate-500">{selected.description}</p>
      ) : null}
    </div>
  );
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>("connection");
  const [settings, setSettings] = useState<PlatformSettings | null>(null);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [apiKeyDraft, setApiKeyDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);

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

  useEffect(() => {
    request<PlatformSettings>("/v1/admin/settings")
      .then((data) => {
        setSettings(data);
        if (data.api_key_configured) {
          void loadModels();
        }
      })
      .catch((err) => setError(err.message));
  }, []);

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
    if (
      (activeTab === "connection" || activeTab === "models") &&
      !settings.api_key_configured &&
      !apiKeyDraft.trim()
    ) {
      setError("ابتدا کلید API سرویس را در تب اتصال AISERVICE ذخیره کنید.");
      return;
    }
    if (activeTab === "models" && models.length) {
      const selections = [
        ["مدل ASR", settings.asr_model, asrModels],
        ["مدل تحلیل", settings.llm_model, llmModels],
        ["مدل دستیار", settings.chat_model, llmModels],
        ["مدل تصمیم‌گیری", settings.decision_model, decisionModels],
        ["مدل fallback تصمیم‌گیری", settings.decision_fallback_model, decisionModels],
        ["مدل embedding", settings.embedding_model, embeddingModels],
      ] as const;
      const invalid = selections.find(([, value, options]) => {
        if (!options.length) return false;
        const selected = options.find((model) => model.id === value);
        return !selected || selected.available === false;
      });
      if (invalid) {
        setError(`${invalid[0]} باید از فهرست مدل‌های آماده AISERVICE انتخاب شود.`);
        return;
      }
    }
    try {
      const body: Record<string, string | boolean | number> = {};
      if (activeTab === "connection") {
        body.voicesanj_base_url = settings.voicesanj_base_url;
        body.llm_provider = settings.llm_provider;
        body.asr_provider = settings.asr_provider;
        if (apiKeyDraft.trim()) {
          body.api_key = normalizeApiKey(apiKeyDraft);
        }
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
        });
        if (settings.embedding_model.trim()) {
          body.embedding_model = settings.embedding_model;
        }
      } else if (activeTab === "audio") {
        Object.assign(body, {
          audio_preprocessing_enabled: settings.audio_preprocessing_enabled,
          audio_denoiser_model: settings.audio_denoiser_model,
          audio_enhancement_model: settings.audio_enhancement_model,
          analysis_concurrency: settings.analysis_concurrency,
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
      setNotice("ذخیره شد.");
      if (
        saved.api_key_configured &&
        (activeTab === "connection" || activeTab === "models")
      ) {
        await loadModels();
      }
    } catch (err) {
      setError((err as Error).message);
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
                setActiveTab(tab.id);
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
          value={settings.llm_model}
          models={llmModels}
          onChange={(llm_model) => setSettings({ ...settings, llm_model })}
        />
        <select className="input mt-2" value={settings.analysis_route} disabled>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
        </select>
      </div>

      <div className={activeTab === "models" ? "" : "hidden"}>
        <ModelSelect
          id="assistant-model"
          label="مدل دستیار سازمانی"
          value={settings.chat_model}
          models={llmModels}
          onChange={(chat_model) => setSettings({ ...settings, chat_model })}
        />
        <select className="input mt-2" value={settings.chat_route} onChange={(event) => setSettings({ ...settings, chat_route: event.target.value as PlatformSettings["chat_route"] })}>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
          <option value="synchronous">/v1/chat/completions — پاسخ مستقیم AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/chat/completions — 9Router از AISERVICE</option>
        </select>
      </div>

      <section className={`${activeTab === "models" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">تصمیم‌گیری محلی AISERVICE</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">مدل اصلی و fallback را از مدل‌های واقعاً قابل دسترس AISERVICE انتخاب کنید.</p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <ModelSelect id="decision-model" label="مدل اصلی" value={settings.decision_model} models={decisionModels} onChange={(decision_model) => setSettings({ ...settings, decision_model })} />
          <ModelSelect id="decision-fallback-model" label="مدل fallback" value={settings.decision_fallback_model} models={decisionModels} onChange={(decision_fallback_model) => setSettings({ ...settings, decision_fallback_model })} />
        </div>
        <div>
          <label className="label" htmlFor="decision-threshold">حداقل اطمینان برای استفاده از مدل اصلی</label>
          <input id="decision-threshold" className="input" type="number" min="0" max="1" step="0.01" value={settings.decision_confidence_threshold} onChange={(event) => setSettings({ ...settings, decision_confidence_threshold: Number(event.target.value) })} />
        </div>
        <select className="input" value={settings.decision_route} disabled>
          <option value="typed">/v1/decisions — تصمیم‌گیری typed AISERVICE</option>
        </select>
      </section>

      <section className={`${activeTab === "models" ? "" : "hidden"} space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4`}>
        <div>
          <h2 className="font-bold text-slate-900">Embedding و بازیابی برداری</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">فقط مدل‌های embedding اعلام‌شده توسط AISERVICE نمایش داده می‌شوند؛ شناسه فرضی یا نصب‌نشده ذخیره نمی‌شود.</p>
        </div>
        <ModelSelect id="embedding-model" label="مدل Embedding" value={settings.embedding_model} models={embeddingModels} onChange={(embedding_model) => setSettings({ ...settings, embedding_model })} />
        <select className="input" value={settings.embedding_route} disabled>
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
