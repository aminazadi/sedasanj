<?php
require __DIR__ . '/../lib/Web.php';
$_SESSION = array();
$token = SedaSanjWeb::token();
if (strlen($token) !== 64 || !SedaSanjWeb::valid($token) || SedaSanjWeb::valid('') || SedaSanjWeb::valid(str_repeat('a', 64))) { throw new Exception('CSRF validation failed'); }
require_once __DIR__ . '/../lib/Process.php';
$output = SedaSanjProcess::run(array(PHP_BINARY, '-r', 'echo stream_get_contents(STDIN);'), 'input with $() and quotes', 3);
if ($output !== 'input with $() and quotes') { throw new Exception('stdin must be literal'); }
try { SedaSanjProcess::run(array(PHP_BINARY, '-r', 'sleep(3);'), '', 0.1); throw new Exception('timeout was not enforced'); }
catch (Exception $exception) { if ($exception->getMessage() !== 'SS-SYS-1011') { throw $exception; } }
echo "Legacy bridge and CSRF passed\n";
