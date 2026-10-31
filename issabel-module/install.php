<?php
if (!defined('ISSABELPBX_IS_AUTH')) { die('No direct script access allowed'); }
if (version_compare(PHP_VERSION, '5.4.0', '<')
    || (!is_file('/etc/issabelpbx.conf') && !is_file('/etc/asterisk/issabelpbx.conf'))
    || !function_exists('getversion') || !preg_match('/^2\.(11|12)\./', (string) getversion())) {
    error_log('SS-SYS-1010: Use the package matching the installed PBX and check the compatibility guide.');
    echo 'SS-SYS-1010: بسته مخصوص مرکز تلفن خود را دریافت و جدول سازگاری را بررسی کنید.';
    return false;
}
// Installation through the GUI intentionally requires a separate root activation.
return true;
