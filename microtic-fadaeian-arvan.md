خوشحالم که ارتباط پایدار و کامل برقرار شد، محمد امین. در ادامه مستندات جامع، فنی و مرحله‌به‌مرحله پیاده‌سازی Multi-WAN با پورت فورواردینگ روی MikroTik CHR در زیرساخت ابری آروان به همراه کالبدشکافی عیب‌یابی‌ها آورده شده است.

---

# مستند فنی پیکربندی و عیب‌یابی Multi-WAN و Port Forwarding در MikroTik CHR (Arvan Cloud)

## ۱. معماری و سناریوی شبکه (Network Topology)
* **روتر مرکزی:** MikroTik CHR (میزبانی شده در ابر آروان)
* **کارت شبکه اصلی (Default WAN):** `ether1` (مسئول اینترنت پیش‌فرض و ترافیک عمومی)
* **کارت شبکه اختصاصی (Dedicated Ingress WAN):** `ether13` (IP: `185.231.182.253/22` | Gateway: `185.231.180.1` | MAC: `fa:16:3e:26:b2:ab`)
* **اینترفیس تونل:** `wg-main` (WireGuard Subnet: `10.77.77.0/24` | روتر: `10.77.77.1`)
* **سرور مقصد نهایی:** Target VPS (`172.29.47.78` متصل از طریق WireGuard)
* **پورت هدف:** TCP/49221 (SSH)

---

## ۲. ریشه‌یابی مشکلات (Root Cause Analysis)

در طول راه‌اندازی با دو مشکل اساسی و زیرساختی مواجه شدیم:

### مشکل اول: باگ لایه شبکه ابری آروان (OpenStack SDN Ingress Failure)
* **شرح مشکل:** روی IP قبلی (`185.231.180.160` روی `ether3`)، خروجی اینترنت (Egress) برقرار بود، اما هیچ پکتی از اینترنت (Ingress) به کارت شبکه ماشین مجازی تحویل داده نمی‌شد.
* **علت فنی:** در معماری OpenStack Neutron، بایندر پورت‌های مجازی و جدول مسیردهی سوئیچ مجازی به سمت پورت اینترفیس دچار اختلال شده بود؛ در نتیجه ترافیک ورودی پیش از رسیدن به ماشین دراپ می‌شد.
* **راهکار:** حذف IP و کارت شبکه قبلی و تخصیص یک IP و پورت شبکه جدید در پنل آروان.

### مشکل دوم: مسیریابی نامتقارن و مسدودسازی توسط Anti-Spoofing آروان (Asymmetric Routing)
* **شرح مشکل:** پکت SSH از `ether13` وارد می‌شد، به سرور مقصد روی تونل وایرگارد (`wg-main`) می‌رفت و سرور مقصد پاسخ می‌داد؛ اما پاسخ به جای خروج از `ether13`، از طریق گیت‌وی پیش‌فرض روی `ether1` ارسال می‌شد و ارتباط قطع می‌شد (Timeout).
* **علت فنی:** به دلیل فعال بودن مکانیزم‌های امنیتی لایه مجازی‌سازی (Anti-MAC/IP Spoofing) در ابر آروان، اگر پکتی با Source IP مربوط به اینترفیس `ether13` از کارت شبکه `ether1` خارج شود، سوئیچ مجازی OpenStack آن را بلافاصله دراپ می‌کند.
* **راهکار:** استفاده از Policy Based Routing (PBR) بر پایه Connection Tracking و روتینگ‌مارک روی ترافیک برگشتی از `wg-main`.

---

## ۳. مراحل گام‌به‌گام پیاده‌سازی (Full Implementation Guide)

### مرحله ۱: اقدامات در پنل ابر آروان
1. ایجاد یا الصاق کارت شبکه جدید (Attach Interface) با آی‌پی عمومی به سرور ابری.
2. اطمینان از قرارگیری کارت شبکه در گروه فایروالی باز (مانند `centralized_arDefault` یا باز بودن پورت‌های ورودی لازم).
3. یادداشت مشخصات کارت شبکه شامل: **IP** ،**Subnet** ،**Gateway** و **MAC Address**.

---

### مرحله ۲: شناسایی اینترفیس در میکروتیک
بررسی نام تخصیص‌یافته به مک‌آدرس کارت شبکه جدید:
```routeros
/interface ethernet print where mac-address="FA:16:3E:26:B2:AB"
```
*(در این سناریو نام اینترفیس `ether13` شناسایی شد).*

---

### مرحله ۳: آدرس‌دهی و ایجاد جدول مسیریابی مستقل (PBR)
برای جلوگیری از تداخل گیت‌وی این اینترفیس با گیت‌وی اصلی روتر:
```routeros
/ip address add address=185.231.182.253/22 interface=ether13

/routing table add name=to-ether13 fib

/ip route add dst-address=0.0.0.0/0 gateway=185.231.180.1%ether13 routing-table=to-ether13
```

---

### مرحله ۴: نشانه‌گذاری ترافیک و هدایت مسیر برگشت (Mangle & Tracking)
ثبت کانکشن‌های ورودی از اینترفیس جدید و اجبار پکت‌های برگشتی از سمت تونل به خروج از همان اینترفیس:
```routeros
/ip firewall mangle add chain=prerouting in-interface=ether13 connection-state=new action=mark-connection new-connection-mark=ether13_conn passthrough=yes

/ip firewall mangle add chain=prerouting in-interface=wg-main connection-mark=ether13_conn action=mark-routing new-routing-mark=to-ether13 passthrough=no
```

---

### مرحله ۵: ترجمه آدرس شبکه (NAT)
1. فوروارد پورت به سرور مقصد روی تونل (**Dst-NAT**):
```routeros
/ip firewall nat add chain=dstnat in-interface=ether13 protocol=tcp dst-port=49221 action=dst-nat to-addresses=172.29.47.78 to-ports=49221
```

2. ماسکراید پکت به سمت سرور داخلی جهت پایداری سورس‌روتینگ (**Src-NAT**):
```routeros
/ip firewall nat add chain=srcnat dst-address=172.29.47.78 protocol=tcp dst-port=49221 action=masquerade
```

---

## ۴. چک‌لیست عیب‌یابی سریع (Troubleshooting Commands)

در صورت بروز اختلال در سناریوهای مشابه:

1. **بررسی ورود ترافیک از اینترنت:**
   ```routeros
   /tool sniffer quick interface=ether13 port=49221
   ```
2. **بررسی چرخه کامل رفت‌وبرگشت پکت بین اینترفیس‌ها:**
   ```routeros
   /tool sniffer quick port=49221
   ```
3. **بررسی برقراری روتینگ تیبل و ARP:**
   ```routeros
   /ip arp print where interface=ether13
   /ip route print where routing-table=to-ether13
   ```
