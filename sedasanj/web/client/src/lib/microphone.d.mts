export type MicrophoneErrorCode = "denied" | "no_device" | "busy" | "constraints" | "unknown";
export function isEmbeddedBrowser(userAgent: string): boolean;
export function microphoneSupportIssue(support: { isSecureContext: boolean; hasGetUserMedia: boolean; hasMediaRecorder: boolean }): "insecure" | "unsupported" | null;
export function classifyMicrophoneError(error: unknown): MicrophoneErrorCode;
export function microphoneErrorMessage(code: MicrophoneErrorCode, options?: { embedded?: boolean }): string;
export function speechErrorMessage(code: string | undefined, options?: { embedded?: boolean }): string;
export function requestMicrophone(mediaDevices: MediaDevices): Promise<MediaStream>;
