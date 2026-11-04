import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const component = await readFile(new URL("../src/components/JalaseNegarPairing.tsx", import.meta.url), "utf8");
const settings = await readFile(new URL("../src/pages/AccountSettings.tsx", import.meta.url), "utf8");
const profile = await readFile(new URL("../src/pages/Profile.tsx", import.meta.url), "utf8");
const api = await readFile(new URL("../../../apps/api/app/routers/meetings.py", import.meta.url), "utf8");

test("account settings read the device list from the API items envelope", () => {
  const endpoint = api.slice(api.indexOf('async def list_devices('), api.indexOf('@router.delete("/devices/{device_id}"'));
  assert.match(endpoint, /"items":\s*\[/);
  assert.match(component, /request<\{ items: MeetingDevice\[\] \}>\("\/v1\/meetings\/devices"\)/);
  assert.match(component, /setDevices\(response\.items\)/);
});

test("pairing is exposed under the integrations query tab and removed from the profile", () => {
  assert.match(settings, /searchParams\.get\("tab"\)/);
  assert.match(settings, /tab === "integrations" \? <JalaseNegarPairing \/>/);
  assert.doesNotMatch(profile, /JalaseNegarPairing/);
});
