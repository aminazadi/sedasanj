<?php
// Only one background service may run: a second start must exit at once with SS-SVC-1005.
$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = sys_get_temp_dir() . '/aru-lock-' . getmypid();
foreach (['pending', 'failed', 'state', 'log', 'monitor', 'uploaded'] as $d) { @mkdir("$root/$d", 0755, true); }
file_put_contents("$root/config.ini", "[general]\nendpoint = http://127.0.0.1:9/v1/ingest/calls\napi_key = sk_live_locktestkey12\nverify_tls = false\ntimeout_seconds = 5\n[post_upload]\nmove_dir = $root/uploaded\n[watcher]\nwatch_dir = $root/monitor\nstate_file = $root/state/w.json\n[queue]\nspool_dir = $root/pending\nfailed_dir = $root/failed\n[state]\nstate_file = $root/state/s.json\n[logging]\nlog_file = $root/log/u.log\nlog_level = DEBUG\nuse_syslog = false\n");
$script = escapeshellarg(__DIR__ . '/../engine/bin/service.php');
$env = ['ARU_CONFIG' => "$root/config.ini"] + $_ENV;
$first = proc_open([PHP_BINARY, __DIR__ . '/../engine/bin/service.php'], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $p, null, $env);
for ($i = 0; $i < 50 && !is_file("$root/state/service.lock"); $i++) { usleep(100000); }
usleep(500000);
putenv("ARU_CONFIG=$root/config.ini");
exec(escapeshellarg(PHP_BINARY) . " $script 2>&1", $out, $code);
proc_terminate($first);
$log = (string) @file_get_contents("$root/log/u.log");
exec('rm -rf ' . escapeshellarg($root));
if ($code !== 1 || strpos($log, 'SS-SVC-1005') === false) { $fail("second instance did not refuse (exit $code): " . implode("\n", $out)); }
echo "Service lock passed.\n";
