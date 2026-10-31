import type { ContactImportReport } from '../types';
export function csvRecords(file: Blob): AsyncGenerator<{text: string; line: number; progress: number}>;
export function csvCells(record: string, delimiter: string): string[];
export function phoneKey(raw: string): string | null;
export function importContacts(file: Blob, mode: 'skip' | 'update', dryRun: boolean, send: (body: FormData) => Promise<ContactImportReport>, onProgress: (percent: number, text: string) => void): Promise<ContactImportReport>;
