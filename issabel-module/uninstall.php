<?php
if (!defined('ISSABELPBX_IS_AUTH')) { die('No direct script access allowed'); }
// Stop delivery immediately when the administrator uninstalls from the GUI.
if (is_file('/etc/sedasanj-recuploader-update/issabel-active')) {
    require_once __DIR__ . '/lib/Process.php';
    try { SedaSanjProcess::run(array('sudo', '-n', '/usr/local/sbin/sedasanj-issabel-control', 'stop'), '', 20); }
    catch (Exception $error) { error_log('SS-SYS-1004: Run uninstall.sh as root to finish removal.'); return false; }
}
// Data and queue are retained. Root cleanup is performed by uninstall.sh.
return true;
