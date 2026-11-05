import React from "react";
import accessOptions from "./panel-access-options.json";
import { createRoot } from "react-dom/client";
import StaffRoleEditor from "../../src/components/StaffRoleEditor";
import EditOrganizationUser from "../../../client/src/components/EditOrganizationUser";
import "../../src/index.css";

const root = createRoot(document.getElementById("root")!);
const writes: Array<{ url: string; body: Record<string, any> }> = [];
let extensionFailure = false;
let writeFailure = false;
let saved = 0;
let primary = false;
const tick = () => new Promise(resolve => setTimeout(resolve, 50));
function check(value: unknown, message: string) { if (!value) throw new Error(message); }
window.fetch = async (input, init) => {
  const url = String(input);
  if (url.endsWith("/v1/auth/panel-access-options")) return new Response(JSON.stringify(accessOptions));
  if (url.endsWith("/v1/extensions")) {
    return new Response(JSON.stringify(extensionFailure ? { error: { code: "internal" } } : [
      { id: "one", extension: "201", pbx_name: "Sales", user_name: null },
      { id: "two", extension: "202", pbx_name: "Support", user_name: null },
    ]), { status: extensionFailure ? 500 : 200 });
  }
  if (init?.method === "PATCH") {
    writes.push({ url, body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify(writeFailure
      ? { error: { code: "quota_exceeded", message: "Quota" } } : {}), { status: writeFailure ? 402 : 200 });
  }
  return new Response(JSON.stringify({ id: "member", email: `phone-${"1234567890".repeat(12)}@accounts.sedasanj.ir`, role: primary ? "org_admin" : "viewer", is_primary_admin: primary, panel_permissions: null, extension: null, mobile_number: null, display_name: "Member" }));
};
function set(element: HTMLInputElement | HTMLSelectElement, value: string) {
  const prototype = element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
  element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
}
async function member(key: string) {
  root.render(<EditOrganizationUser key={key} userId="member" onClose={() => {}} onSaved={async () => { saved++; }} />);
  await tick(); await tick();
}
async function run() {
  await member("first");
  const role = document.querySelector("select")!;
  check(role.options.length === 3, "All organization roles must be selectable");
  check(document.querySelectorAll('[role="switch"]').length === 20, "All panel sections must use project switches");
  check(document.querySelectorAll('input[type="checkbox"]').length === 0, "Permission checkboxes must be replaced");
  const callSwitch = document.querySelector<HTMLButtonElement>('[role="switch"][aria-label="تماس‌ها و پیام‌های صوتی"]')!;
  callSwitch.click(); await tick();
  check(callSwitch.getAttribute("aria-checked") === "false", "Each section must be independently switchable");
  set(role, "operator"); await tick();
  document.querySelector("form")!.requestSubmit(); await tick();
  check(writes.length === 0, "An operator without numbers must not be saved");
  const extension = document.querySelector<HTMLInputElement>("input[list]")!;
  check(extension.list?.options.length === 2, "Synced extensions must populate the dropdown");
  check(extension.list?.options[0].textContent?.includes("Sales"), "PBX names must be displayed");
  set(extension, "201"); await tick();
  document.querySelector("form")!.requestSubmit(); await tick();
  check(writes.at(-1)?.body.role === "operator" && writes.at(-1)?.body.extension === "201", "Synced extension and new role must be saved together");
  check(!writes.at(-1)?.body.panel_permissions?.includes("calls"), "Custom section selection must be persisted with the member");
  check(saved === 1, "Successful save must reload the member list");

  await member("custom");
  set(document.querySelector<HTMLInputElement>("input[list]")!, "۹۹۹"); await tick();
  set(document.querySelector("select")!, "org_admin"); await tick();
  document.querySelector("form")!.requestSubmit(); await tick();
  check(writes.at(-1)?.body.extension === "999" && writes.at(-1)?.body.role === "org_admin", "Custom extensions and Persian digits must work");

  extensionFailure = true;
  await member("fallback");
  check(document.body.textContent?.includes("شماره را دستی وارد کنید"), "Fetch failure must offer manual entry");
  set(document.querySelector<HTMLInputElement>("input[list]")!, "888"); await tick();
  extensionFailure = false;
  const retry = [...document.querySelectorAll("button")].find(button => button.textContent === "دریافت دوبارهٔ داخلی‌ها")!;
  retry.click(); await tick();
  check(document.querySelector<HTMLInputElement>("input[list]")!.value === "888", "Retry must preserve custom extension values");
  check(document.querySelector<HTMLInputElement>("input[list]")!.list?.options.length === 2, "Retry must repopulate synced extensions");
  set(document.querySelector("select")!, "operator"); await tick();
  writeFailure = true;
  document.querySelector("form")!.requestSubmit(); await tick();
  check(document.body.textContent?.includes("ظرفیت اپراتورهای پلن"), "Quota errors must give an actionable Persian message");
  writeFailure = false;

  root.render(<StaffRoleEditor target={{ id: "staff", email: "staff@example.com", role: "support" }}
    onClose={() => {}} onSaved={async () => { saved++; }} />);
  await tick();
  check(document.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled, "Unchanged staff role must not submit");
  set(document.querySelector("select")!, "super_admin");
  set(document.querySelector<HTMLInputElement>('input[type="password"]')!, "test-proof");
  set(document.querySelector<HTMLInputElement>('input[inputmode="numeric"]')!, "۱۲۳۴۵۶"); await tick();
  document.querySelector("form")!.requestSubmit(); await tick();
  const last = writes.at(-1)!;
  check(last.url.endsWith("/staff/staff/role") && last.body.role === "super_admin", "Staff role API must be called");
  check(last.body.current_password === "test-proof" && last.body.totp_code === "123456", "Sensitive proof and normalized TOTP must be sent");
  check(saved === 3, "Both successful member saves and staff save must reload their lists");
  primary = true;
  await member("primary");
  check(document.querySelector<HTMLSelectElement>("select")!.disabled, "Primary admin role must be locked");
  check([...document.querySelectorAll<HTMLButtonElement>('[role="switch"]')].every(button => button.disabled), "Primary admin permissions must be locked");
  const dialog = document.querySelector("dialog")!;
  check(dialog.scrollWidth <= dialog.clientWidth + 1, "Dialog must not overflow horizontally");
  const form = dialog.querySelector("form")!;
  const content = [...form.children].filter(element => !element.classList.contains("demo-dialog-actions"));
  check(content.every(element => element.scrollWidth <= element.clientWidth + 2), "Long emails and permission controls must fit their content boxes");
}
run().then(() => { document.getElementById("results")!.textContent = JSON.stringify({ passed: true }); })
  .catch(error => { document.getElementById("results")!.textContent = JSON.stringify({ passed: false, error: String(error) }); });
