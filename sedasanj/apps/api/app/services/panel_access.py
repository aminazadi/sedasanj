"""Per-user panel sections, layered on top of the existing role and data scopes."""

from collections.abc import Sequence
from typing import Literal, Protocol

from app.errors import ApiError

PanelSection = Literal[
    "dashboard",
    "calls",
    "meetings",
    "contacts",
    "extensions",
    "tasks",
    "assistant",
    "reports",
    "scores",
    "billing",
    "scoring_settings",
    "ai_settings",
    "kpi_settings",
    "users",
    "integrations",
    "data",
    "setup",
    "pbx_servers",
    "releases",
    "api_docs",
]

SECTION_LABELS: dict[PanelSection, str] = {
    "dashboard": "داشبورد",
    "calls": "تماس‌ها و پیام‌های صوتی",
    "meetings": "جلسات",
    "contacts": "دفترچه تلفن",
    "extensions": "داخلی‌ها",
    "tasks": "کارها",
    "assistant": "دستیار تماس‌ها",
    "reports": "گزارش‌های زمان‌بندی‌شده",
    "scores": "امتیازها",
    "billing": "اعتبار و اشتراک",
    "scoring_settings": "تنظیمات امتیاز عملکرد",
    "ai_settings": "تنظیمات هوش مصنوعی",
    "kpi_settings": "تنظیمات KPI و تیم‌ها",
    "users": "مدیریت کاربران و دسترسی‌ها",
    "integrations": "اتصال‌ها، کلید API و وب‌هوک",
    "data": "بک‌آپ، بازیابی و خروجی داده‌ها",
    "setup": "راه‌اندازی",
    "pbx_servers": "سرورهای تلفنی",
    "releases": "تغییرات نسخه‌ها",
    "api_docs": "مستندات API",
}
ADMIN_ONLY = frozenset(
    {
        "reports",
        "scoring_settings",
        "ai_settings",
        "kpi_settings",
        "users",
        "data",
        "pbx_servers",
    }
)
NON_OPERATOR = frozenset({"billing", "setup", "releases"})


def role_sections(role: str) -> list[PanelSection]:
    return [
        key
        for key in SECTION_LABELS
        if (role == "org_admin" or key not in ADMIN_ONLY)
        and (role != "operator" or key not in NON_OPERATOR)
    ]


def effective_sections(role: str, selected: Sequence[str] | None) -> list[PanelSection]:
    allowed = role_sections(role)
    return allowed if selected is None else [key for key in allowed if key in selected]


class PanelPrincipal(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def panel_permissions(self) -> frozenset[str] | None: ...


def assert_can_delegate(
    principal: PanelPrincipal, role: str, selected: Sequence[str] | None
) -> None:
    if (
        principal.panel_permissions is not None
        and not set(effective_sections(role, selected)) <= principal.panel_permissions
    ):
        raise denied()


def denied() -> ApiError:
    return ApiError(
        "panel_access_denied",
        "دسترسی این بخش برای حساب شما فعال نیست؛ از مدیر سازمان بخواهید دسترسی را بررسی کند.",
    )


def request_sections(path: str, method: str) -> tuple[str, ...] | None:
    """Return alternative section grants; () means own-account access, None is unclassified."""
    path = path.rstrip("/")
    if path in {"/v1/auth/me", "/v1/auth/panel-access-options", "/v1/account"} or any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in ("/v1/auth/totp", "/v1/auth/phone")
    ):
        return ()
    if path == "/v1/extensions" and method == "GET":
        return ("extensions", "users", "contacts")
    if path == "/v1/operator-score-rubric" and method == "GET":
        return ("scoring_settings", "scores", "calls")
    if path == "/v1/kpi/dashboard" or path == "/v1/analytics/summary":
        return ("dashboard",)
    if path.startswith("/v1/meetings/devices"):
        return ("integrations",)
    if path == "/v1/module/installations":
        return ("pbx_servers", "setup")
    if path == "/v1/quick-demo/sessions" or path.startswith("/v1/quick-demo/sessions/"):
        return ("calls",)
    prefixes: tuple[tuple[str, str], ...] = (
        ("/v1/auth/users", "users"),
        ("/v1/auth/api-keys", "integrations"),
        ("/v1/calls", "calls"),
        ("/v1/contacts", "contacts"),
        ("/v1/extensions", "extensions"),
        ("/v1/tasks", "tasks"),
        ("/v1/billing", "billing"),
        ("/v1/checkout", "billing"),
        ("/v1/orders", "billing"),
        ("/v1/invoices", "billing"),
        ("/v1/subscription", "billing"),
        ("/v1/installation-requests", "setup"),
        ("/v1/webhooks", "integrations"),
        ("/v1/account", "data"),
        ("/v1/assistant", "assistant"),
        ("/v1/operator-score-rubric", "scoring_settings"),
        ("/v1/operator-ranking-visibility", "scoring_settings"),
        ("/v1/operator-scores", "scores"),
        ("/v1/scheduled-reports", "reports"),
        ("/v1/kpi", "kpi_settings"),
        ("/v1/meetings", "meetings"),
        ("/v1/org/ai-instructions", "ai_settings"),
        ("/v1/module/releases", "releases"),
    )
    return next(
        (
            (section,)
            for prefix, section in prefixes
            if path == prefix or path.startswith(prefix + "/")
        ),
        None,
    )


def assert_request_access(principal: PanelPrincipal, path: str, method: str) -> None:
    if principal.panel_permissions is None:
        return
    sections = request_sections(path, method)
    if sections == ():
        return
    if sections is None or not principal.panel_permissions.intersection(sections):
        raise denied()
