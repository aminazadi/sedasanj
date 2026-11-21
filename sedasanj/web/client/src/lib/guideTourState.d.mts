export interface GuideTourStep {
  id: string;
  roles: readonly string[];
  target: string | null;
  title: string;
  body: string;
}

export interface TourStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function tourStorageKey(role: string): string;
export function hasCompletedTour(role: string, storage: TourStorage): boolean;
export function markTourCompleted(role: string, storage: TourStorage): void;
export function getStepsForRole<T extends { roles: readonly string[] }>(steps: readonly T[], role: string): T[];
