<?php
/* Authenticated legacy endpoint; no FreePBX BMO dependency. */
ob_start();
require_once __DIR__ . '/lib/IssabelAuth.php';
$admin = dirname(dirname(__DIR__)); $root = dirname($admin);
if (SedaSanjIssabelAuth::integrated($root)) {
    SedaSanjIssabelAuth::session($admin);
    if (!SedaSanjIssabelAuth::allowed($root)) { ob_end_clean(); header('HTTP/1.1 403 Forbidden'); exit; }
    // The bypass is used only after independently authenticating the native session and ACL.
    $bootstrap_settings['issabelpbx_auth'] = false;
}
chdir($admin);
require is_file('/etc/issabelpbx.conf') ? '/etc/issabelpbx.conf' : '/etc/asterisk/issabelpbx.conf';
require_once __DIR__ . '/lib/Web.php';
SedaSanjWeb::authorize();
ob_end_clean();
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
if ($_SERVER['REQUEST_METHOD'] !== 'POST' || !SedaSanjWeb::valid(isset($_POST['csrf']) ? $_POST['csrf'] : '')) {
    header('HTTP/1.1 403 Forbidden'); echo json_encode(array('ok' => false, 'code' => 'SS-CFG-1003')); exit;
}
$payload = isset($_POST['payload']) ? $_POST['payload'] : '';
if (!is_string($payload) || strlen($payload) > 65536) { header('HTTP/1.1 400 Bad Request'); exit; }
$request = json_decode($payload, true);
if (!is_array($request)) { header('HTTP/1.1 400 Bad Request'); exit; }
try { echo SedaSanjWeb::call($request); }
catch (Exception $error) { echo json_encode(array('ok' => false, 'code' => 'SS-SYS-1011', 'message' => 'فعال‌سازی و مسیر PHP موتور را بررسی کنید.')); }
