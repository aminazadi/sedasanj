export type ScriptManifest = Record<"head" | "body", Array<Record<string, string>>>;
export function appendSiteScripts(manifest: ScriptManifest, scope: string, options: {
  document: Document;
  isActive: () => boolean;
  reportFailure: () => void;
  timeout?: number;
}): Promise<void>;
