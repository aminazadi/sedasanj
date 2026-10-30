export const BILLING_ERRORS: Record<string, string>;
export function billingErrorMessage(
  code: string | undefined,
  serverMessage: string | undefined,
  fallback: string,
): string;
