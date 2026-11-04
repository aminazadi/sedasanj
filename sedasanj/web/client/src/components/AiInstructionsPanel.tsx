import { useCallback } from "react";
import AiInstructionsEditor, { type AiInstructions } from "@cbi/web-shared/components/AiInstructionsEditor";
import { request } from "../api";

export default function AiInstructionsPanel() {
  const load = useCallback(() => request<AiInstructions>("/v1/org/ai-instructions"), []);
  const save = useCallback(
    (changes: Partial<Pick<AiInstructions, "coach" | "meeting">>) =>
      request<AiInstructions>("/v1/org/ai-instructions", { method: "PUT", body: changes }),
    [],
  );
  return <AiInstructionsEditor load={load} save={save} audience="organization" />;
}
