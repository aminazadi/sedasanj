export function normalizeOtp(value: string): string {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)))
    .replace(/\D/g, "")
    .slice(0, 6);
}

export function isCompleteOtp(value: string): boolean {
  return /^[0-9]{6}$/.test(value);
}
