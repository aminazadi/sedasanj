import TwoFactorSettings from "../components/TwoFactorSettings";
import ToggleSwitch from "@cbi/web-shared/components/ToggleSwitch";
import { useEffect, useMemo, useState } from "react";
import { fmt, request } from "../api";
import { ErrorBox, Loading } from "../components/Widgets";
import type { PlatformSettings, ProviderModel } from "../types";

const LLM_KINDS = new Set(["llm", "language", "chat", "text"]);
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

export default function Settings() {
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
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setError(null);
    setNotice(null);
    if (!settings.api_key_configured && !apiKeyDraft.trim()) {
      setError("کلید API سرویس تحلیل متن را وارد کنید.");
      return;
    }
    try {
      const body: Record<string, string | boolean | number> = {
        voicesanj_base_url: settings.voicesanj_base_url,
        llm_provider: settings.llm_provider,
        asr_provider: settings.asr_provider,
        asr_base_url: settings.asr_base_url,
        asr_model: settings.asr_model,
        llm_model: settings.llm_model,
        chat_model: settings.chat_model,
        extract_prompt: settings.extract_prompt,
        assistant_instructions: settings.assistant_instructions,
        audio_preprocessing_enabled: settings.audio_preprocessing_enabled,
        audio_denoiser_model: settings.audio_denoiser_model,
        audio_enhancement_model: settings.audio_enhancement_model,
        analysis_concurrency: settings.analysis_concurrency,
        decision_model: settings.decision_model,
        decision_fallback_model: settings.decision_fallback_model,
        decision_confidence_threshold: settings.decision_confidence_threshold,
        embedding_base_url: settings.embedding_base_url,
        embedding_model: settings.embedding_model,
        asr_route: settings.asr_route,
        analysis_route: settings.analysis_route,
        chat_route: settings.chat_route,
        decision_route: settings.decision_route,
        embedding_route: settings.embedding_route,
      };
      if (apiKeyDraft.trim()) {
        body.api_key = normalizeApiKey(apiKeyDraft);
      }
      const saved = await request<PlatformSettings>("/v1/admin/settings", {
        method: "PATCH",
        body,
      });
      setSettings(saved);
      setApiKeyDraft("");
      setNotice("ذخیره شد.");
      if (saved.api_key_configured) {
        await loadModels();
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!settings) return error ? <ErrorBox message={error} /> : <Loading />;

  return (
    <div className="max-w-2xl space-y-5">
      <TwoFactorSettings />
    <form className="card space-y-5" onSubmit={save}>
      <h1 className="font-bold">تنظیمات مدل‌ها</h1>
      <ErrorBox message={error} />
      {notice ? <div className="text-sm text-emerald-700">{notice}</div> : null}

      <div>
        <label className="label" htmlFor="llm-provider">ارائه‌دهنده تحلیل متن و دستیار</label>
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

      <div>
        <label className="label">کلید API سرویس تحلیل متن</label>
        <input
          className="input"
          dir="ltr"
          type="password"
          autoComplete="off"
          placeholder={
            settings.api_key_configured
              ? `کلید فعلی: ${settings.api_key_hint || "••••"} (برای تغییر بنویسید)`
              : "کلید API سرویس تحلیل متن VoiceSanj"
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

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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

      <div>
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

      <div className="flex items-center justify-between gap-2">
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
      {modelsError ? <ErrorBox message={modelsError} /> : null}

      <section className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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

      <div>
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

      <div>
        <label className="label">مدل پیاده‌سازی صوت (ASR)</label>
        <input
          className="input"
          dir="ltr"
          list="asr-model-options"
          value={settings.asr_model}
          onChange={(event) => setSettings({ ...settings, asr_model: event.target.value })}
          required
        />
        <datalist id="asr-model-options">
          {asrModels.map((model) => <option key={model.id} value={model.id}>{modelOptionLabel(model)}</option>)}
        </datalist>
        <p className="mt-1 text-xs text-slate-500">از فهرست انتخاب کنید یا شناسه مدل دلخواه را وارد کنید.</p>
      </div>

      <div>
        <label className="label">مدل زبانی (LLM)</label>
        <input
          className="input"
          dir="ltr"
          list="llm-model-options"
          value={settings.llm_model}
          onChange={(event) => setSettings({ ...settings, llm_model: event.target.value })}
          required
        />
        <datalist id="llm-model-options">
          {llmModels.map((model) => <option key={model.id} value={model.id}>{modelOptionLabel(model)}</option>)}
        </datalist>
        <p className="mt-1 text-xs text-slate-500">از فهرست انتخاب کنید یا شناسه مدل دلخواه را وارد کنید.</p>
        <select className="input mt-2" value={settings.analysis_route} disabled>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
        </select>
      </div>

      <div>
        <label className="label">مدل چت سازمانی</label>
        <input
          className="input"
          dir="ltr"
          list="llm-model-options"
          value={settings.chat_model}
          onChange={(event) => setSettings({ ...settings, chat_model: event.target.value })}
          required
        />
        <p className="mt-1 text-xs text-slate-500">از فهرست انتخاب کنید یا شناسه مدل دلخواه را وارد کنید.</p>
        <select className="input mt-2" value={settings.chat_route} onChange={(event) => setSettings({ ...settings, chat_route: event.target.value as PlatformSettings["chat_route"] })}>
          <option value="durable">/v1/chat/tasks — صف durable AISERVICE</option>
          <option value="synchronous">/v1/chat/completions — پاسخ مستقیم AISERVICE</option>
          <option value="ninerouter">/v1/ninerouter/chat/completions — 9Router از AISERVICE</option>
        </select>
      </div>

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <h2 className="font-bold text-slate-900">تصمیم‌گیری محلی AISERVICE</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">GLiNER2.5 مدل اصلی و Laya Multilingual مسیر confidence پایین است.</p>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <input className="input" dir="ltr" value={settings.decision_model} onChange={(event) => setSettings({ ...settings, decision_model: event.target.value })} />
          <input className="input" dir="ltr" value={settings.decision_fallback_model} onChange={(event) => setSettings({ ...settings, decision_fallback_model: event.target.value })} />
          <input className="input" type="number" min="0" max="1" step="0.01" value={settings.decision_confidence_threshold} onChange={(event) => setSettings({ ...settings, decision_confidence_threshold: Number(event.target.value) })} />
        </div>
        <select className="input" value={settings.decision_route} disabled>
          <option value="typed">/v1/decisions — تصمیم‌گیری typed AISERVICE</option>
        </select>
      </section>

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div>
          <h2 className="font-bold text-slate-900">Embedding و بازیابی برداری</h2>
          <p className="mt-1 text-xs leading-6 text-slate-500">سرویس OpenAI-compatible برای وکتور کردن خلاصه تماس‌ها و پرسش‌های دستیار.</p>
        </div>
        <input className="input" dir="ltr" placeholder="BAAI/bge-m3" value={settings.embedding_model} onChange={(event) => setSettings({ ...settings, embedding_model: event.target.value })} />
        <select className="input" value={settings.embedding_route} disabled>
          <option value="ninerouter">/v1/ninerouter/embeddings — 9Router از AISERVICE</option>
        </select>
      </section>


      <section className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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
      <section className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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
        ذخیره
      </button>
    </form>
    </div>
  );
}
