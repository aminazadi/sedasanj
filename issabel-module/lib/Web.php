<?php
require_once __DIR__ . '/Process.php';
require_once __DIR__ . '/IssabelAuth.php';
class SedaSanjWeb
{
    public static function authorize() {
        $root = dirname(dirname(dirname(dirname(__DIR__))));
        if (SedaSanjIssabelAuth::integrated($root)) {
            $allowed = defined('ISSABELPBX_IS_AUTH') && ISSABELPBX_IS_AUTH && SedaSanjIssabelAuth::allowed($root);
        } else {
            $allowed = defined('ISSABELPBX_IS_AUTH') && ISSABELPBX_IS_AUTH
                && isset($_SESSION['AMP_user']) && is_object($_SESSION['AMP_user'])
                && method_exists($_SESSION['AMP_user'], 'checkSection') && $_SESSION['AMP_user']->checkSection('recuploader');
        }
        if (!$allowed) { header('HTTP/1.1 403 Forbidden'); exit; }
    }
    public static function token() {
        if (empty($_SESSION['sedasanj_csrf'])) {
            $strong = false; $bytes = openssl_random_pseudo_bytes(32, $strong);
            if ($bytes === false || !$strong) { throw new Exception('SS-SYS-1011'); }
            $_SESSION['sedasanj_csrf'] = bin2hex($bytes);
        }
        return $_SESSION['sedasanj_csrf'];
    }
    public static function valid($value) {
        $expected = self::token();
        if (!is_string($value) || strlen($value) !== strlen($expected)) { return false; }
        $difference = 0;
        for ($i = 0; $i < strlen($value); $i++) { $difference |= ord($value[$i]) ^ ord($expected[$i]); }
        return $difference === 0;
    }
    public static function call($request) {
        $php = trim((string) @file_get_contents('/etc/sedasanj-recuploader-update/php-path'));
        if ($php === '' || !is_executable($php)) { throw new Exception('SS-SYS-1004'); }
        $timeout = isset($request['op']) && $request['op'] === 'update' ? 360 : 45;
        $request['php_web'] = PHP_VERSION;
        return SedaSanjProcess::run(array($php, dirname(__DIR__) . '/bin/control.php'), json_encode($request), $timeout);
    }
}
