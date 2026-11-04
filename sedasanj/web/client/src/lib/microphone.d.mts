export type MicrophoneErrorCode = "denied" | "no_device" | "busy" | "constraints" | "inactive" | "unknown";
export type MicrophoneSupportIssue = "insecure" | "policy" | "unsupported";
export type QuickDemoMicrophoneIssue = MicrophoneErrorCode | MicrophoneSupportIssue | "pending";
export function isEmbeddedBrowser(userAgent: string): boolean;
export function microphoneSupportIssue(support: {
  isSecureContext: boolean;
  policy?: { allowsFeature?: (name: string) => boolean };
  hasGetUserMedia: boolean;
  hasMediaRecorder: boolean;
}): MicrophoneSupportIssue | null;
export function classifyMicrophoneError(error: unknown): MicrophoneErrorCode;
export function microphoneErrorMessage(code: MicrophoneErrorCode, options?: { embedded?: boolean }): string;
export const quickDemoMicrophoneIssues: Record<QuickDemoMicrophoneIssue, { code: string; message: string }>;
export function speechErrorMessage(code: string | undefined, options?: { embedded?: boolean }): string;
export function requestMicrophone(mediaDevices: MediaDevices): Promise<MediaStream>;
