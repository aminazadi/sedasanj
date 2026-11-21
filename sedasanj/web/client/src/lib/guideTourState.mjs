const STORAGE_VERSION = "v1";

export function tourStorageKey(role) {
  return `sedasanj.client.tour.${STORAGE_VERSION}.${role}`;
}

export function hasCompletedTour(role, storage) {
  try {
    return storage.getItem(tourStorageKey(role)) === "1";
  } catch {
    return false;
  }
}

export function markTourCompleted(role, storage) {
  try {
    storage.setItem(tourStorageKey(role), "1");
  } catch {
    // Storage can be blocked (private mode); the tour then just replays every visit.
  }
}

export function getStepsForRole(steps, role) {
  return steps.filter((step) => step.roles.includes(role));
}
