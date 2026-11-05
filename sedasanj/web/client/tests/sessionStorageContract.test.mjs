import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const api = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");
const auth = await readFile(new URL("../src/auth.tsx", import.meta.url), "utf8");
const saveBlock = api.slice(api.indexOf("save(pair"), api.indexOf("clear()"));

test("the access token is kept in memory and the refresh token is never stored by scripts", () => {
  assert.match(api, /let accessToken: string \| null = null;/);
  assert.doesNotMatch(saveBlock, /pair\.refresh_token/);
  assert.doesNotMatch(saveBlock, /setItem\(\w+_(ACCESS|REFRESH)_KEY, pair/);
});

test("browser requests opt in to the HttpOnly refresh cookie", () => {
  assert.match(api, /"X-Auth-Transport": "cookie"/);
  assert.match(api, /\.\.\.TRANSPORT_HEADERS/);
});

test("logout and boot rely on the session hint, not a stored token", () => {
  assert.doesNotMatch(auth, /tokens\.refresh\(\)/);
  assert.match(auth, /tokens\.hasSession\(\)/);
});
