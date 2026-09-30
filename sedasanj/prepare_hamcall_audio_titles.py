#!/usr/bin/env python3

from pathlib import Path

DIRECTORY = Path.home() / "Downloads" / "hamcall_audios"
RENAMES = {
    "نمونه-پشتیبانی-هست-اینجا-خبازی.wav": "support-khabazi.wav",
    "نمونه-پشتیبانی-همیان-جباری.wav": "support-jabbari.wav",
    "مریم-جهانی-1-تولده-بازاریابی.wav": "marketing-jahani-birthday.wav",
    "مریم-یوسفی-همسایه-بازاریابی.wav": "marketing-yousefi-neighbor.wav",
    "تریبون1.wav": "sales-triboon-01.wav",
    "نمونه-بازرایابی-فرازمند-افشانی.wav": "sales-farazmand-afshani.wav",
    "صیادزاده-2-زندگی-باآیه-ها-فروش-ساده.wav": "sales-sayyadzadeh-life-with-verses.wav",
    "وویس-5-لیمومی.wav": "sales-limoumi-05.wav",
    "میرزامحمدی-1-ترب-اطلاع-رسانی.wav": "notification-mirzammadi-torob.wav",
    "متنو1.wav": "notification-matno-01.wav",
    "مبینا-صفوی-دیجی-پی-اطلاع-رسانی.wav": "notification-safavi-digipay.wav",
    "نمونه-نظرسنجی-شب-شمخانی.wav": "survey-shab-shamkhani.wav",
    "نمونه-نظرسنجی-باسلام-محمدی.wav": "survey-baasalam-mohammadi.wav",
    "نجفی-تارا-وصول-مطالبات.wav": "collections-najafi-tara.wav",
    "رکابدار-جی-اسم-پی-وصول-مطالبات.wav": "collections-rakabdar-gsm.wav",
}


def main():
    missing = [source for source in RENAMES if not (DIRECTORY / source).is_file()]
    occupied = [target for target in RENAMES.values() if (DIRECTORY / target).exists()]
    if missing:
        raise SystemExit(f"Missing source files: {', '.join(missing)}")
    if occupied:
        raise SystemExit(f"Target files already exist: {', '.join(occupied)}")
    for source, target in RENAMES.items():
        (DIRECTORY / source).rename(DIRECTORY / target)


if __name__ == "__main__":
    main()
