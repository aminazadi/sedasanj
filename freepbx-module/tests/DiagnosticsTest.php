<?php
// doctor.php and support-bundle.php: structured report, stable codes, and no secrets or numbers in the bundle.
$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = sys_get_temp_dir() . '/aru-diag-' . getmypid();
foreach (['pending', 'failed', 'state', 'log', 'monitor', 'uploaded'] as $d) { @mkdir("$root/$d", 0755, true); }
$secret = 'sk_live_diagnosticsecret99';
file_put_contents("$root/config.ini", <<<INI
[general]
endpoint = https://127.0.0.1:9/v1/ingest/calls
api_key = $secret
api_key_b64 = c2tfbGl2ZV9kaWFnbm9zdGljc2VjcmV0OTk=
archive_password = hunter2hunter2
verify_tls = false
timeout_seconds = 5
[post_upload]
move_dir = $root/uploaded
[watcher]
watch_dir = $root/monitor
state_file = $root/state/watcher_state.json
[queue]
spool_dir = $root/pending
failed_dir = $root/failed
[state]
state_file = $root/state/state.json
[logging]
log_file = $root/log/uploader.log
log_level = DEBUG
use_syslog = false
INI);
file_put_contents("$root/log/uploader.log", "2026-10-29 10:00:00+0000 [1] ERROR aru.test: Upload failed for 09121234567 key $secret | code=SS-UPL-0401 src=09121234567\n");
putenv("ARU_CONFIG=$root/config.ini");
$bin = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/../engine/bin/');

exec($bin . 'doctor.php --json --no-network 2>&1', $out, $code);
$report = json_decode(implode("\n", $out), true);
if (!is_array($report) || !isset($report['checks']) || !is_bool($report['ok'])) { $fail('doctor --json output: ' . implode("\n", $out)); }
$byId = [];
foreach ($report['checks'] as $c) { $byId[$c['id']] = $c; }
if (($byId['php']['status'] ?? '') !== 'ok' || ($byId['storage']['status'] ?? '') !== 'ok') { $fail('php/storage checks'); }
if (($report['recent_codes']['SS-UPL-0401'] ?? 0) !== 1) { $fail('recent log codes not summarised'); }
if (strpos(implode("\n", $out), $secret) !== false) { $fail('doctor leaked the API key'); }

exec($bin . 'doctor.php --no-network 2>&1', $text, $code);
if (strpos(implode("\n", $text), '[OK  ] PHP CLI') === false) { $fail('doctor text output'); }

$bundle = "$root/bundle.tar.gz";
exec($bin . 'support-bundle.php --out=' . escapeshellarg($bundle) . ' 2>&1', $bout, $code);
if ($code !== 0 || !is_file($bundle)) { $fail('bundle not created: ' . implode("\n", $bout)); }
mkdir("$root/x");
exec('tar -xzf ' . escapeshellarg($bundle) . ' -C ' . escapeshellarg("$root/x") . ' 2>&1', $tout, $code);
$all = '';
foreach (glob("$root/x/sedasanj-support/*") as $f) { $all .= file_get_contents($f); }
foreach (['config.ini', 'doctor.json', 'log-current.txt', 'module.xml'] as $expected) {
	if (!is_file("$root/x/sedasanj-support/$expected")) { $fail("bundle lacks $expected"); }
}
foreach ([$secret, 'hunter2hunter2', 'c2tfbGl2ZV9kaWFnbm9zdGljc2VjcmV0OTk=', '09121234567'] as $leak) {
	if (strpos($all, $leak) !== false) { $fail("bundle leaks $leak"); }
}
if (strpos(file_get_contents("$root/x/sedasanj-support/log-current.txt"), 'SS-UPL-0401') === false) { $fail('bundle log lost the error code'); }
exec('rm -rf ' . escapeshellarg($root));
echo "Diagnostics passed.\n";
