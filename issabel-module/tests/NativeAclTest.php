<?php
require __DIR__ . '/../lib/IssabelAuth.php';
$root = sys_get_temp_dir() . '/sj-acl-' . uniqid();
mkdir($root); mkdir($root . '/libs'); mkdir($root . '/configs');
file_put_contents($root . '/libs/misc.lib.php', "<?php\n");
file_put_contents($root . '/configs/default.conf.php', '<?php $arrConf["issabel_dsn"]["acl"] = "fixture";');
file_put_contents($root . '/libs/paloSantoDB.class.php', '<?php class paloDB { public $errMsg=""; function __construct($dsn) {} }');
file_put_contents($root . '/libs/paloSantoACL.class.php', '<?php class paloACL { public $errMsg=""; function __construct($db) {} function authenticateUser($u,$p) { return $u === "operator" && $p === "test-only"; } function hasModulePrivilege($u,$m,$s) { return !empty($GLOBALS["fixture_granted"]) && $m === "pbxadmin" && $s === "recuploader"; } }');
$_SESSION = array(); $cwd = getcwd();
if (SedaSanjIssabelAuth::allowed($root)) { throw new Exception('Anonymous native session accepted'); }
$_SESSION = array('issabel_user'=>'operator','issabel_pass'=>'wrong');
$GLOBALS['fixture_granted']=true;
if (SedaSanjIssabelAuth::allowed($root)) { throw new Exception('Wrong native password accepted'); }
$_SESSION['issabel_pass']='test-only'; $GLOBALS['fixture_granted']=false;
if (SedaSanjIssabelAuth::allowed($root)) { throw new Exception('Missing module ACL accepted'); }
$GLOBALS['fixture_granted']=true;
if (!SedaSanjIssabelAuth::allowed($root)) { throw new Exception('Native module grant rejected'); }
if (getcwd() !== $cwd) { throw new Exception('ACL check changed working directory'); }
echo "Native Issabel authentication and module ACL passed\n";
