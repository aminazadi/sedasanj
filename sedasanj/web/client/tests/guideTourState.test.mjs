import assert from "node:assert/strict";
import test from "node:test";
import { getStepsForRole, hasCompletedTour, markTourCompleted, tourStorageKey } from "../src/lib/guideTourState.mjs";

function memoryStorage() {
  const data = new Map();
  return { getItem: (key) => (data.has(key) ? data.get(key) : null), setItem: (key, value) => data.set(key, value) };
}

function throwingStorage() {
  return {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };
}

test("storage key is versioned and distinct per role", () => {
  assert.equal(tourStorageKey("org_admin"), "sedasanj.client.tour.v1.org_admin");
  assert.notEqual(tourStorageKey("org_admin"), tourStorageKey("operator"));
});

test("a role's tour is not completed until marked, then stays completed", () => {
  const storage = memoryStorage();
  assert.equal(hasCompletedTour("org_admin", storage), false);
  markTourCompleted("org_admin", storage);
  assert.equal(hasCompletedTour("org_admin", storage), true);
  // Marking one role's tour does not affect another role's.
  assert.equal(hasCompletedTour("operator", storage), false);
});

test("a blocked storage (private mode) fails closed instead of throwing", () => {
  const storage = throwingStorage();
  assert.equal(hasCompletedTour("org_admin", storage), false);
  assert.doesNotThrow(() => markTourCompleted("org_admin", storage));
});

test("getStepsForRole keeps order and only the steps available to that role", () => {
  const steps = [
    { id: "welcome", roles: ["org_admin", "operator"] },
    { id: "billing", roles: ["org_admin"] },
    { id: "scores", roles: ["operator"] },
    { id: "profile", roles: ["org_admin", "operator"] },
  ];
  assert.deepEqual(getStepsForRole(steps, "org_admin").map((step) => step.id), ["welcome", "billing", "profile"]);
  assert.deepEqual(getStepsForRole(steps, "operator").map((step) => step.id), ["welcome", "scores", "profile"]);
  assert.deepEqual(getStepsForRole(steps, "viewer"), []);
});
