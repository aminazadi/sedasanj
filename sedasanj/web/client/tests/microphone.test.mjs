import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyMicrophoneError,
  isEmbeddedBrowser,
  microphoneErrorMessage,
  microphoneSupportIssue,
  requestMicrophone,
  speechErrorMessage,
} from "../src/lib/microphone.mjs";

test("support issue separates insecure pages from missing APIs", () => {
  assert.equal(microphoneSupportIssue({ isSecureContext: false, hasGetUserMedia: true, hasMediaRecorder: true }), "insecure");
  assert.equal(microphoneSupportIssue({ isSecureContext: true, hasGetUserMedia: true, hasMediaRecorder: false }), "unsupported");
  assert.equal(microphoneSupportIssue({ isSecureContext: true, hasGetUserMedia: true, hasMediaRecorder: true }), null);
});

test("errors are classified by DOMException name", () => {
  assert.equal(classifyMicrophoneError({ name: "NotAllowedError" }), "denied");
  assert.equal(classifyMicrophoneError({ name: "NotFoundError" }), "no_device");
  assert.equal(classifyMicrophoneError({ name: "NotReadableError" }), "busy");
  assert.equal(classifyMicrophoneError({ name: "OverconstrainedError" }), "constraints");
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

test("requestMicrophone retries with plain audio after a constraint failure", async () => {
  const calls = [];
  const devices = {
    async getUserMedia(constraints) {
      calls.push(constraints);
      if (calls.length === 1) throw Object.assign(new Error("x"), { name: "OverconstrainedError" });
      return "stream";
    },
  };
  assert.equal(await requestMicrophone(devices), "stream");
  assert.deepEqual(calls[1], { audio: true });
});

test("requestMicrophone does not retry when permission is denied", async () => {
  let count = 0;
  const devices = { async getUserMedia() { count += 1; throw Object.assign(new Error("x"), { name: "NotAllowedError" }); } };
  await assert.rejects(requestMicrophone(devices), { name: "NotAllowedError" });
  assert.equal(count, 1);
});
