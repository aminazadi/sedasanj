<?php
require_once __DIR__ . '/lib/Web.php';
SedaSanjWeb::authorize();
$csrf = SedaSanjWeb::token();
$active = is_file('/etc/sedasanj-recuploader-update/issabel-active');
?>
<link rel="stylesheet" href="/admin/modules/recuploader/assets/admin.css">
<div id="sj-issabel" dir="rtl" data-csrf="<?php echo htmlspecialchars($csrf, ENT_QUOTES, 'UTF-8'); ?>">
  <h2>صداسنج</h2>
  <p>مدیریت ضبط و ارسال تماس‌های ایزابل</p>
  <?php if (!$active): ?>
  <div class="sj-notice">فعال‌سازی مدیر سیستم لازم است. PHP وب ایزابل را تغییر ندهید؛ مسیر PHP مستقل موتور را در فرمان زیر وارد کنید.</div>
  <pre dir="ltr">bash /var/www/html/admin/modules/recuploader/activate.sh /opt/remi/php74/root/usr/bin/php</pre>
  <?php endif; ?>
  <nav id="sj-tabs"></nav>
  <div id="sj-message" role="status"></div>
  <div id="sj-content"></div>
</div>
<script src="/admin/modules/recuploader/assets/admin.js" defer></script>
