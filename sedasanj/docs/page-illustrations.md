# تصاویر هیرو صفحه‌های عمومی

هر صفحه فایل مخصوص خودش را دارد؛ برای تعویض، فقط فایل را با **همین نام** جایگزین کنید (کد تغییری نمی‌خواهد).
هر چهار فایل با تصویرهای اختصاصی (هم‌سبک تصویر صفحهٔ اصلی) جایگزین شده‌اند.

| صفحه | فایل در `web/client/src/assets/` |
|---|---|
| درباره ما | `page-hero-about.webp` |
| تماس با ما | `page-hero-contact.webp` |
| مقالات / راهنما | `page-hero-help.webp` |
| قوانین و حریم خصوصی | `page-hero-legal.webp` |

مشخصات: نسبت ۲:۱ (۱۵۰۰×۷۵۰)، پس‌زمینهٔ شفاف، خروجی WebP (`cwebp -q 85`)، بدون هیچ متن روی تصویر.

## پیشوند مشترک همهٔ پرامپت‌ها (برای هم‌سبک ماندن با تصویر صفحهٔ اصلی)

> Hand-inked architectural illustration with soft watercolor fills, in the exact style of the reference image
> (attach `hero-office.webp` as style reference). Palette: only deep green, mid green, pale sage and white,
> thin dark-green ink outlines, thin steel-frame structure, hanging plants, Tehran Milad Tower skyline through the
> glass wall. People are Iranian (some women in dark-green hijab, men with beards, white shirts). No text, no logos,
> no Latin or Persian letters anywhere, transparent/white background, wide 2:1 composition, no border.

## پرامپت هر صفحه (بعد از پیشوند)

- **about:** A bright team room where about a dozen colleagues of a call-center analytics company collaborate: a long
  shared table with laptops, a whiteboard with sticky notes and a simple diagram of a sound wave turning into a
  bar chart, two people shaking hands near the window, a plant wall. Warm, human, "who we are" mood.
- **contact:** A friendly reception and support lounge: a front desk with an operator wearing a headset, a visitor
  being welcomed, a wall-mounted phone and an envelope/chat-bubble motif drawn as plain objects (no text), a sofa
  corner with coffee, a few operators on calls in the background. Approachable "talk to us" mood.
- **help:** A quiet knowledge-base corner: a tall bookshelf of binders, an open large manual on a desk, a support
  engineer showing a monitor with a checklist and a magnifier icon to a colleague, a server rack with small green
  lights behind glass, a plant. Calm "we help you solve it" mood.
- **legal:** A formal meeting room: a long table with folders and a signed document, a person reading a contract,
  a shield and a padlock drawn as a wall relief or desk object (no text), a scale-of-justice statuette, shelves of
  files. Serious but warm "trust and privacy" mood.

## تبدیل و جایگزینی

```bash
cwebp -q 85 -resize 1500 750 input.png -o sedasanj/web/client/src/assets/page-hero-about.webp
```
