import assert from "node:assert/strict";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const { chromium } = await import(process.env.PASSWORD_PLAYWRIGHT_MODULE ?? "playwright-core");
const cwd = fileURLToPath(new URL("..", import.meta.url));
const bundle = await build({
  stdin: {
    contents: `import React from 'react'; import {createRoot} from 'react-dom/client';
      import PasswordChange from './src/components/PasswordChange';
      createRoot(document.getElementById('root')).render(<PasswordChange mobile="09120000000" />);`,
    resolveDir: cwd, loader: "tsx",
  },
  bundle: true, write: false, jsx: "automatic", outfile: "/fixture.js", loader: { ".svg": "dataurl" },
  plugins: [{ name: "password-fixture", setup(builder) {
    builder.onResolve({ filter: /^\.\.\/api$/ }, () => ({ path: "api", namespace: "fixture" }));
    builder.onResolve({ filter: /^\.\.\/auth$/ }, () => ({ path: "auth", namespace: "fixture" }));
    builder.onResolve({ filter: /^\.\/Widgets$/ }, () => ({ path: "widgets", namespace: "fixture" }));
    builder.onLoad({ filter: /.*/, namespace: "fixture" }, ({ path }) => ({ loader: "tsx", resolveDir: cwd, contents:
      path === "api" ? `export class ApiError extends Error { constructor(code, message) { super(message); this.code = code; } }
        export const fmt = { latinDigits: value => value.replace(/[۰-۹]/g, d => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d))).replace(/[٠-٩]/g, d => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d))) };
        export async function request(path, options) {
          const response = await fetch('/mock' + path, {method: options.method, body: JSON.stringify(options.body)});
          const result = await response.json();
          if (!response.ok) throw new ApiError(result.code, result.message);
          return result;
        }`
      : path === "auth" ? "export const useAuth = () => ({acceptSession: () => { window.acceptedSession = true; }});"
      : "export const ErrorBox = ({message}) => message ? <div role='alert'>{message}</div> : null;",
    }));
  } }],
});
const requests = [];
let changeResult = "totp";
const server = createServer(async (request, response) => {
  if (request.url.startsWith("/mock")) {
    let body = "";
    for await (const chunk of request) body += chunk;
    const payload = body ? JSON.parse(body) : {};
    requests.push({ path: request.url, payload });
    response.setHeader("Content-Type", "application/json");
    let result;
    if (request.url.endsWith("/password/request")) result = { otp_id: `otp-${requests.length}`, resend_after: 0, requires_totp: false };
    else if (request.url.endsWith("/verify")) {
      if (payload.code === "123456") {
        response.statusCode = 400;
        result = { code: "otp_invalid", message: "کد نادرست است؛ دوباره وارد کنید." };
      } else result = { verified_token: "fixture-grant" };
    } else if (changeResult !== "success") {
      response.statusCode = 400;
      result = changeResult === "totp"
        ? { code: "password_change_totp_required", message: "کد ورود دومرحله‌ای را وارد کنید." }
        : { code: "password_change_verification_required", message: "تأیید منقضی شده؛ دوباره کد بگیرید." };
    } else result = { access_token: "fixture-access", refresh_token: "fixture-refresh" };
    response.end(JSON.stringify(result));
    return;
  }
  const asset = bundle.outputFiles.find(file => file.path.endsWith(request.url === "/fixture.css" ? ".css" : ".js"));
  response.setHeader("Content-Type", request.url === "/fixture.js" ? "text/javascript" : request.url === "/fixture.css" ? "text/css" : "text/html; charset=utf-8");
  response.end(request.url.startsWith("/fixture.") ? asset.text
    : '<html dir="rtl"><meta charset="utf-8"><link rel="stylesheet" href="/fixture.css"><div id="root"></div><script src="/fixture.js"></script></html>');
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const passwords = page.locator('input[type="password"]');
  const digits = page.getByRole("group", { name: "کد شش‌رقمی پیامک" }).locator("input");
  const verifyRequests = () => requests.filter(item => item.path.endsWith("/verify"));
  const changeRequests = () => requests.filter(item => item.path.endsWith("/password/change"));
  const change = () => page.getByRole("button", { name: "تغییر گذرواژه", exact: true }).click();
  const send = () => page.getByRole("button", { name: "ارسال کد تأیید", exact: true }).click();
  await send();
  await digits.first().waitFor();
  assert.equal(await digits.count(), 6);
  assert.equal(await passwords.count(), 0);
  await digits.first().fill("۱۲۳۴۵");
  assert.equal(verifyRequests().length, 0);
  await digits.nth(5).fill("۶");
  await page.getByRole("alert").waitFor();
  assert.equal(await passwords.count(), 0, "Rejected OTP must not expose password fields");
  await page.waitForTimeout(150);
  assert.equal(verifyRequests().length, 1, "Rejected OTP must not retry automatically");
  await digits.first().fill("۶");
  await passwords.first().waitFor();
  assert.equal(verifyRequests().length, 2);
  assert.equal(await digits.count(), 0);
  assert.equal(await passwords.count(), 2);
  assert.equal(changeRequests().length, 0, "OTP verification must not change the password");
  await passwords.first().fill("fixture-password");
  await passwords.nth(1).fill("different-password");
  await change();
  await page.getByRole("alert").waitFor();
  assert.equal(changeRequests().length, 0);
  await passwords.nth(1).fill("fixture-password");
  await change();
  const totp = page.locator('input[pattern="[0-9]{6}"]');
  await totp.waitFor();
  assert.equal(await passwords.count(), 2, "TOTP errors must preserve the verified step");
  changeResult = "expired";
  await totp.fill("۶۵۴۳۲۱");
  await change();
  await page.getByRole("button", { name: "ارسال کد تأیید", exact: true }).waitFor();
  assert.equal(await passwords.count(), 0, "Expired grants must return to verification");
  changeResult = "success";
  await send();
  await digits.first().fill("۶۵۴۳۲۱");
  await passwords.first().waitFor();
  assert.equal(await passwords.first().inputValue(), "");
  await passwords.first().fill("fixture-password");
  await passwords.nth(1).fill("fixture-password");
  await change();
  await page.getByRole("status").waitFor();
  assert.equal(await page.evaluate(() => window.acceptedSession), true);
  assert.equal(await passwords.count(), 0);
  assert.equal(changeRequests().at(-1).payload.verified_token, "fixture-grant");
  console.log("Password OTP stages, rejection, normalization, TOTP, expiry and success passed.");
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
