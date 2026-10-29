import { useCallback, useRef, useState, type ReactNode } from "react";

export interface SensitiveProof {
  current_password: string;
  totp_code: string | null;
}

/**
 * Asks for the operator's password (and the authenticator code) before an action that changes what
 * every customer PBX installs. Usage: `const [ask, dialog] = useSensitiveAction();` then
 * `const proof = await ask("..."); if (!proof) return;` and render `{dialog}`.
 */
export function useSensitiveAction(): [(message: string) => Promise<SensitiveProof | null>, ReactNode] {
  const [message, setMessage] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const resolver = useRef<((proof: SensitiveProof | null) => void) | null>(null);

  const ask = useCallback((text: string) => {
    setPassword("");
    setCode("");
    setMessage(text);
    return new Promise<SensitiveProof | null>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  function finish(proof: SensitiveProof | null) {
    setMessage(null);
    resolver.current?.(proof);
    resolver.current = null;
  }

  const dialog =
    message === null ? null : (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" role="dialog" aria-modal="true">
        <form
          className="w-full max-w-sm space-y-3 rounded-xl bg-white p-5 shadow-xl"
          onSubmit={(e) => {
            e.preventDefault();
            finish({ current_password: password, totp_code: code.trim() || null });
          }}
        >
          <p className="text-sm text-slate-700">{message}</p>
          <div>
            <label className="label">گذرواژهٔ فعلی شما</label>
            <input className="input" type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div>
            <label className="label">کد دو مرحله‌ای (اگر فعال است)</label>
            <input className="input" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-ghost" onClick={() => finish(null)}>
              انصراف
            </button>
            <button type="submit" className="btn" disabled={!password}>
              تأیید
            </button>
          </div>
        </form>
      </div>
    );
  return [ask, dialog];
}
