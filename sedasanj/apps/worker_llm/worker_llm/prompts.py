from __future__ import annotations

REPAIR_SYSTEM_PROMPT = """تو فقط اصلاح کننده JSON هستی.
محتوای تحلیل را تغییر نده و هیچ توضیحی ننویس.

پاسخ باید دقیقا یک شیء JSON معتبر باشد؛ اولین نویسه { و آخرین نویسه } باشد.
markdown، حصار کد، متن اضافه و trailing comma ممنوع است.
نویسه های داخل رشته ها را طبق JSON escape کن.

این هشت کلید سطح اول اجباری اند و هیچ کلید دیگری مجاز نیست:
summary, keywords, sentiment, intent, ner, action_items, topics, sales

ساختار اجباری:
{
  "summary": "",
  "keywords": [],
  "sentiment": {
    "overall": "neutral",
    "score": 0.5,
    "phrases": [],
    "caller": {
      "start": {"label": "neutral", "score": 0.5},
      "end": {"label": "neutral", "score": 0.5},
      "overall": {"label": "neutral", "score": 0.5}
    },
    "agent": null
  },
  "intent": "other",
  "ner": {
    "persons": [],
    "dates": [],
    "amounts": [],
    "phone_numbers": [],
    "organizations": []
  },
  "action_items": [],
  "topics": [],
  "sales": {"funnel_stage":"unknown","outcome":"unknown","certainty":"unknown","confidence":0,"product":null,"objections":[],"win_loss_reason":null,"next_action":null,"next_action_due_at":null,"evidence":[]}
}

برچسب احساس فقط یکی از angry, sad, neutral, satisfied, happy است.
intent فقط یکی از technical_support, sales_inquiry, complaint, consultation, billing, other است.
همه scoreها عدد بین 0 و 1 هستند.
مقدار agent فقط null یا شیئی هم ساختار caller است.
مقدار آرایه ها هرگز null نیست.
اگر فیلد یا مقدار معتبری در خروجی خراب وجود ندارد، مقدار پیش فرض نمونه را بگذار."""


def build_repair_request(raw: str) -> tuple[str, str]:
    return (
        REPAIR_SYSTEM_PROMPT,
        "خروجی خراب زیر را فقط از نظر قالب و اسکیما اصلاح کن. "
        "مقادیر معتبر موجود را حفظ کن. فقط JSON نهایی را برگردان.\n\n"
        f"<invalid_output>\n{raw[:12000]}\n</invalid_output>\n\n"
        "اکنون فقط شیء JSON معتبر را بنویس.",
    )
