import DOMPurify from "dompurify";
import type { ReleaseEntry } from "@cbi/web-shared/components/ReleaseTimeline";
import { request } from "./api";

/** Second layer after the server allowlist; release notes are rendered as HTML. */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target"], FORBID_TAGS: ["style", "img", "iframe"] });
}

export interface ModuleInstallation {
  product?: string;
  issabel_version?: string | null;
  framework_version?: string | null;
  id: string;
  host_uuid: string;
  hostname: string | null;
  freepbx_version: string | null;
  php_version: string | null;
  module_version: string;
  service_status: string | null;
  last_seen_at: string;
  last_update_status: "started" | "succeeded" | "failed" | "rolled_back" | null;
  last_update_error: string | null;
  last_update_at: string | null;
  update_available: boolean;
  latest_version: string | null;
}

export interface ModuleFleet {
  items: ModuleInstallation[];
  latest: ReleaseEntry | null;
  outdated: number;
}

let fleetRequest: Promise<ModuleFleet> | null = null;

/** Shared by the layout banner and the servers page so one navigation makes one request. */
export function loadModuleFleet(force = false): Promise<ModuleFleet> {
  if (force || !fleetRequest) {
    fleetRequest = request<ModuleFleet>("/v1/module/installations").catch((error) => {
      fleetRequest = null;
      throw error;
    });
  }
  return fleetRequest;
}

export function loadReleases(product = "freepbx-recuploader"): Promise<{ items: ReleaseEntry[] }> {
  return request<{ items: ReleaseEntry[] }>(`/v1/module/releases?product=${encodeURIComponent(product)}`);
}
