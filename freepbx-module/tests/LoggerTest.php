<?php
// Logger: format, redaction, number masking, line-forging protection, rotation, catalog.
require __DIR__ . '/../engine/autoload.php';

use Engine\ErrorCatalog;
use Engine\Logger;

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$dir = sys_get_temp_dir() . '/aru-logger-' . getmypid();
@mkdir($dir);
$file = "$dir/test.log";
$cfg = ['general' => ['api_key' => 'sk_live_supersecretvalue123', 'archive_password' => 'hunter2hunter2'],
	'logging' => ['log_file' => $file, 'log_level' => 'DEBUG', 'use_syslog' => false, 'mask_numbers' => true]];
$log = new Logger($cfg, 'aru.test');

$log->coded('SS-UPL-0401', 'Upload failed with key sk_live_supersecretvalue123 and Bearer abcdefgh12345678',
	['src' => '09121234567', 'http_status' => 401, 'note' => "line1\nFAKE ERROR forged", 'pw' => 'hunter2hunter2']);
$log->info('plain');
$out = file_get_contents($file);
foreach (['sk_live_supersecretvalue123', 'abcdefgh12345678', '09121234567', 'hunter2hunter2'] as $secret) {
	if (strpos($out, $secret) !== false) { $fail("leaked $secret"); }
}
if (!preg_match('/\] ERROR aru\.test: Upload failed.* \| code=SS-UPL-0401 src=\*{8}567 http_status=401 /', $out)) { $fail("format: $out"); }
if (substr_count($out, "\n") !== 2) { $fail('control characters were not neutralised'); }
if (!preg_match('/\]\s+(DEBUG|INFO|WARNING|ERROR)\s/', $out)) { $fail('viewer regex'); }
if (substr(sprintf('%o', fileperms($file)), -4) !== '0640') { $fail('log file mode'); }

// Rotation: oversize file is rotated exactly once under the lock.
file_put_contents($file, str_repeat('x', Logger::MAX_BYTES + 10));
$log->info('after rotation');
if (!is_file("$file.1") || filesize($file) > 1000) { $fail('rotation did not happen'); }

// Catalog integrity: codes well-formed, lookup, HTTP and curl mapping.
foreach (ErrorCatalog::ENTRIES as $code => $entry) {
	if (!preg_match('/^SS-[A-Z]{3,4}-\d{4}$/', $code)) { $fail("bad code $code"); }
	if (count($entry) !== 4 || !in_array($entry[0], ['info', 'warning', 'error', 'critical'], true)) { $fail("bad entry $code"); }
}
foreach ([400, 401, 402, 403, 404, 413, 415, 422, 429, 500, 503, 418] as $status) {
	if (!ErrorCatalog::exists(ErrorCatalog::forHttpStatus($status))) { $fail("no code for HTTP $status"); }
}
foreach ([6, 7, 28, 35, 60, 99] as $errno) {
	if (!ErrorCatalog::exists(ErrorCatalog::forCurlErrno($errno))) { $fail("no code for curl $errno"); }
}
if (ErrorCatalog::lookup('SS-UPL-0401')['help_url'] !== 'https://sedasanj.ir/help/errors/SS-UPL-0401') { $fail('help url'); }

array_map('unlink', glob("$dir/*"));
@rmdir($dir);
echo "Logger and error catalog passed.\n";
