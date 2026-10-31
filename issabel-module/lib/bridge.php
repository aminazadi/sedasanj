<?php
/* This file must remain parseable by PHP 5.4. It never loads the engine. */
if (PHP_SAPI !== 'cli') { exit(1); }
$mode = isset($argv[1]) ? $argv[1] : '';
if (!in_array($mode, array('inventory', 'extensions'), true)) { exit(2); }
$bootstrap_settings['issabelpbx_auth'] = false;
$bootstrap = is_file('/etc/issabelpbx.conf') ? '/etc/issabelpbx.conf' : '/etc/asterisk/issabelpbx.conf';
ob_start();
require $bootstrap;
if (!function_exists('core_users_list') && isset($amp_conf['AMPWEBROOT'])) {
    require_once $amp_conf['AMPWEBROOT'] . '/admin/modules/core/functions.inc.php';
}
$rows = function_exists('core_users_list') ? core_users_list() : array();
ob_end_clean();
if ($mode === 'extensions') { echo json_encode($rows); exit; }
if (!function_exists('posix_geteuid') || posix_geteuid() !== 0) { exit(1); }
$release = @file_get_contents('/etc/issabel-release');
if (!preg_match('/\b([45])(?:\.|\b)/', (string) $release, $match)) {
    fwrite(STDERR, "SS-SYS-1010: Cannot identify Issabel 4/5; check /etc/issabel-release.\n"); exit(1);
}
function sj_value($key, $fallback) {
    global $amp_conf;
    return isset($amp_conf[$key]) && $amp_conf[$key] !== '' ? $amp_conf[$key] : $fallback;
}
$inventory = array(
    'product' => 'issabel-recuploader', 'issabel_version' => $match[1],
    'framework_version' => function_exists('getversion') ? getversion() : '',
    'legacy_ready' => function_exists('proc_open') && function_exists('openssl_random_pseudo_bytes') && function_exists('json_encode'),
    'php_web' => null, 'php_system_version' => PHP_VERSION, 'extensions' => $rows,
    'monitor_dir' => rtrim(sj_value('MIXMON_DIR', sj_value('ASTSPOOLDIR', '/var/spool/asterisk') . '/monitor'), '/'),
    'recording_format' => sj_value('MIXMON_FORMAT', 'wav'),
    'post_hook' => sj_value('MIXMON_POST', ''),
    'webroot' => sj_value('AMPWEBROOT', '/var/www/html'),
    'ampbin' => sj_value('AMPBIN', '/var/lib/asterisk/bin'),
    'cdr' => array('host' => sj_value('CDRDBHOST', sj_value('AMPDBHOST', 'localhost')),
        'port' => (int) sj_value('CDRDBPORT', 3306),
        'database' => sj_value('CDRDBNAME', 'asteriskcdrdb'),
        'table' => sj_value('CDRDBTABLENAME', 'cdr'),
        'user' => sj_value('CDRDBUSER', sj_value('AMPDBUSER', '')),
        'password' => sj_value('CDRDBPASS', sj_value('AMPDBPASS', ''))),
);
echo json_encode($inventory);
