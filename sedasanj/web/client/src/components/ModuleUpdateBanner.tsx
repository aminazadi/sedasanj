import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fmt } from "../api";
import { loadModuleFleet, type ModuleFleet } from "../moduleUpdates";

const DISMISS_KEY = "sedasanj.module-update-dismissed";

function readDismissed(): string | null {
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

/** Org-admin banner when any FreePBX host of the tenant runs an older module than published. */
export default function ModuleUpdateBanner() {
  const [fleet, setFleet] = useState<ModuleFleet | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(readDismissed);

  useEffect(() => {
    loadModuleFleet()
      .then(setFleet)
      .catch(() => setFleet(null));
  }, []);

  const latest = fleet?.latest;
  if (!fleet || !latest || fleet.outdated === 0) return null;
  const security = latest.severity === "security" || latest.severity === "critical";
  if (!security && dismissed === latest.version) return null;

  return (
    <div
      className={`mb-5 flex flex-wrap items-center gap-3 border px-4 py-3 text-sm ${security ? "border-2 border-amber-500 bg-amber-50 text-amber-900" : "border-[color:var(--line)] bg-[#F2F0EF] text-[#3b5739]"}`}
      role="status"
    >
      <span className="font-bold">
        {security ? "به‌روزرسانی مهم ماژول FreePBX: " : "نسخهٔ جدید ماژول FreePBX: "}
        <span dir="ltr" data-keep-latin-digits>v{latest.version}</span>
      </span>
      <span>
        {fmt.int(fleet.outdated)} سرور از {fmt.int(fleet.items.length)} سرور شما هنوز به‌روز نشده است.
      </span>
      <span className="mr-auto flex gap-2">
        <Link className="underline" to={`/module-changelog#v${latest.version}`}>تغییرات</Link>
        <Link className="underline" to="/freepbx-servers">سرورها</Link>
        {security ? null : (
          <button
            type="button"
            className="opacity-70 hover:opacity-100"
            aria-label="بستن"
            onClick={() => {
              try {
                localStorage.setItem(DISMISS_KEY, latest.version);
              } catch {
                /* storage unavailable: dismiss for this view only */
              }
              setDismissed(latest.version);
            }}
          >
            ✕
          </button>
        )}
      </span>
    </div>
  );
}
