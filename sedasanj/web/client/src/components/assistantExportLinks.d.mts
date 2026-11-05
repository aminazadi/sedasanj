import type { Root } from "mdast";
import type { AssistantExportFile, AssistantToolRun } from "../types";
export function exportDownloadPath(file: AssistantExportFile): string;
export function exportFiles(runs: AssistantToolRun[]): AssistantExportFile[];
export function appendExportLinks(tree: Root, files: AssistantExportFile[]): void;
