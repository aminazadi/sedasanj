<?php
if (!defined('ISSABELPBX_IS_AUTH')) { die('No direct script access allowed'); }
require_once __DIR__ . '/lib/Dialplan.php';
function recuploader_get_config($engine) {
    global $ext, $amp_conf;
    if ($engine !== 'asterisk' || !is_file('/etc/sedasanj-recuploader-update/issabel-active')) { return; }
    $post = isset($amp_conf['MIXMON_POST']) ? trim($amp_conf['MIXMON_POST']) : '';
    if ($post !== '' || !SedaSanjDialplan::apply($ext, true, isset($amp_conf['MIXMON_DIR']) && $amp_conf['MIXMON_DIR'] !== '' ? $amp_conf['MIXMON_DIR'] : '/var/spool/asterisk/monitor')) {
        error_log('SS-HOOK-1010: Issabel recording layout or existing post hook conflicts; run Seda Sanj health checks. PBX dialplan preserved.');
        $dir = '/var/lib/asterisk-recording-uploader';
        $temp = tempnam($dir, '.hook-');
        if ($temp !== false) { file_put_contents($temp, 'SS-HOOK-1010'); chmod($temp, 0640); rename($temp, $dir . '/issabel-hook-error'); }
    } else { @unlink('/var/lib/asterisk-recording-uploader/issabel-hook-error'); }
}
