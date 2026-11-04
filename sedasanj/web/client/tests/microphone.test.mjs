import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyMicrophoneError,
  isEmbeddedBrowser,
  microphoneErrorMessage,
  microphoneSupportIssue,
  quickDemoMicrophoneIssues,
  requestMicrophone,
  speechErrorMessage,
} from "../src/lib/microphone.mjs";

test("support issue separates insecure pages from missing APIs", () => {
  assert.equal(microphoneSupportIssue({ isSecureContext: false, hasGetUserMedia: true, hasMediaRecorder: true }), "insecure");
  assert.equal(microphoneSupportIssue({ isSecureContext: true, hasGetUserMedia: true, hasMediaRecorder: false }), "unsupported");
  assert.equal(microphoneSupportIssue({ isSecureContext: true, hasGetUserMedia: true, hasMediaRecorder: true }), null);
});

test("a known permissions policy block is detected without assuming unsupported policy APIs block capture", () => {
  const support = { isSecureContext: true, hasGetUserMedia: true, hasMediaRecorder: true };
  assert.equal(microphoneSupportIssue({ ...support, policy: {} }), null);
  assert.equal(microphoneSupportIssue({ ...support, policy: { allowsFeature: (name) => name === "microphone" } }), null);
  assert.equal(microphoneSupportIssue({ ...support, policy: { allowsFeature: (name) => name !== "microphone" } }), "policy");
});

test("errors are classified by DOMException name", () => {
  assert.equal(classifyMicrophoneError({ name: "NotAllowedError" }), "denied");
  assert.equal(classifyMicrophoneError({ name: "NotFoundError" }), "no_device");
  assert.equal(classifyMicrophoneError({ name: "NotReadableError" }), "busy");
  assert.equal(classifyMicrophoneError({ name: "OverconstrainedError" }), "constraints");
  assert.equal(classifyMicrophoneError({ name: "InvalidStateError" }), "inactive");
  assert.equal(classifyMicrophoneError(null), "unknown");
});

test("in-app browsers are detected, regular browsers are not", () => {
  assert.equal(isEmbeddedBrowser("Mozilla/5.0 (iPhone) AppleWebKit Mobile/15E148 Instagram 300.0"), true);
  assert.equal(isEmbeddedBrowser("Mozilla/5.0 (Linux; Android 13; SM-S911B; wv) AppleWebKit Chrome/120 Mobile Safari"), true);
  assert.equal(isEmbeddedBrowser("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17.0 Mobile Safari/604.1"), false);
  assert.equal(isEmbeddedBrowser("Mozilla/5.0 (Macintosh) AppleWebKit Chrome/120 Safari/537.36"), false);
});

test("denied message tells embedded-browser users to switch browser", () => {
  assert.match(microphoneErrorMessage("denied", { embedded: true }), /Safari یا Chrome/);
  assert.match(microphoneErrorMessage("denied"), /قفل/);
  assert.match(speechErrorMessage("service-not-allowed"), /قفل/);
  assert.equal(speechErrorMessage("no-speech"), "");
});

test("requestMicrophone requests plain audio synchronously on the initial call", async () => {
  const calls = [];
  const devices = {
    async getUserMedia(constraints) {
      calls.push(constraints);
      return "stream";
    },
  };
  const pending = requestMicrophone(devices);
  assert.deepEqual(calls, [{ audio: true }]);
  assert.equal(await pending, "stream");
});

test("quick demo microphone diagnostics have stable codes and actionable messages", () => {
  const codes = Object.values(quickDemoMicrophoneIssues).map(({ code }) => code);
  assert.equal(new Set(codes).size, codes.length);
  assert.equal(quickDemoMicrophoneIssues.denied.code, "quick_demo_mic_denied");
  assert.match(quickDemoMicrophoneIssues.denied.message, /تنظیمات دستگاه/);
  assert.match(quickDemoMicrophoneIssues.pending.message, /نوار آدرس/);
});

test("requestMicrophone does not retry when permission is denied", async () => {
  let count = 0;
  const devices = { async getUserMedia() { count += 1; throw Object.assign(new Error("x"), { name: "NotAllowedError" }); } };
  await assert.rejects(requestMicrophone(devices), { name: "NotAllowedError" });
  assert.equal(count, 1);
});
