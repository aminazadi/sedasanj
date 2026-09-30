from __future__ import annotations

import re

PRIVACY_REFUSAL = (
    "متأسفم، امکان ارائه این اطلاعات در محدوده دسترسی فعلی شما وجود ندارد. "
    "من فقط می‌توانم بر اساس اطلاعاتی که برای حساب شما مجاز شده است کمک کنم."
)

_CROSS_TENANT = re.compile(
    r"(?:سازمان|شرکت|tenant)\s+(?:دیگر|دیگه|سایر|بقیه|another|other)", re.IGNORECASE
)
_CROSS_OPERATOR = re.compile(
    r"(?:اپراتور|کارشناس|operator)\s+(?:دیگر|دیگه|سایر|بقیه|another|other)",
    re.IGNORECASE,
)
_ORGANIZATION_WIDE = re.compile(
    r"(?:کل|تمام|همه(?:ی|ٔ)?)\s+(?:سازمان|شرکت|اپراتورها|کارشناسان)|"
    r"(?:رتبه|رنک|مقایسه).*(?:اپراتورها|کارشناسان)",
    re.IGNORECASE,
)


def must_refuse(question: str, role: str) -> bool:
    normalized = " ".join(question.split())
    if _CROSS_TENANT.search(normalized):
        return True
    return role == "operator" and (
        _CROSS_OPERATOR.search(normalized) or _ORGANIZATION_WIDE.search(normalized)
    ) is not None
