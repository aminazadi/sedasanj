<?php
/* Follow the native Issabel session and pbxadmin ACL without patching the wrapper. */
class SedaSanjIssabelAuth
{
    public static function integrated($root) {
        return is_file($root . '/libs/paloSantoACL.class.php');
    }
    public static function session($admin) {
        require_once $admin . '/libraries/ampuser.class.php';
        if (session_id() !== '' && session_name() !== 'issabelSession') { session_write_close(); }
        if (session_id() === '') { session_name('issabelSession'); session_start(); }
    }
    public static function allowed($root) {
        global $arrConf;
        if (!isset($_SESSION['issabel_user'], $_SESSION['issabel_pass'])
            || !is_string($_SESSION['issabel_user']) || !is_string($_SESSION['issabel_pass'])) { return false; }
        $cwd = getcwd(); chdir($root);
        try {
            require_once $root . '/libs/misc.lib.php';
            require_once $root . '/configs/default.conf.php';
            require_once $root . '/libs/paloSantoDB.class.php';
            require_once $root . '/libs/paloSantoACL.class.php';
            if (!isset($arrConf['issabel_dsn']['acl'])) { chdir($cwd); return false; }
            $database = new paloDB($arrConf['issabel_dsn']['acl']);
            $acl = new paloACL($database);
            $allowed = empty($database->errMsg) && empty($acl->errMsg)
                && $acl->authenticateUser($_SESSION['issabel_user'], $_SESSION['issabel_pass'])
                && $acl->hasModulePrivilege($_SESSION['issabel_user'], 'pbxadmin', 'recuploader');
            chdir($cwd); return $allowed;
        } catch (Exception $exception) { chdir($cwd); return false; }
    }
}
