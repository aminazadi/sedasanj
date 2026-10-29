<?php
require __DIR__ . '/../engine/autoload.php';

use Engine\DependencyCheck;
use Engine\ErrorCatalog;

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$row = function (array $report, string $id) use ($fail) {
	foreach ($report['rows'] as $r) { if ($r['id'] === $id) { return $r; } }
	$fail("no row $id");
};

$healthy = [
	'freepbx_version' => '16.0.40', 'php_web' => '7.4.33', 'php_cli' => '7.4.33',
	'web_extensions' => ['curl' => 1, 'zlib' => 1, 'json' => 1, 'simplexml' => 1],
	'cli_extensions' => ['curl' => 1, 'zlib' => 1, 'json' => 1, 'pdo_sqlite' => 1, 'ctype' => 1, 'pcntl' => 1, 'sodium' => 1],
	'modules' => ['core' => ['status' => 'enabled', 'version' => '16.0.40'], 'callrecording' => ['status' => 'enabled', 'version' => '16.0.3'],
		'cdr' => ['status' => 'enabled', 'version' => '16.0.5'], 'voicemail' => ['status' => 'enabled', 'version' => '16.0.2']],
	'binaries' => ['unzip' => '/usr/bin/unzip', 'sudo' => '/usr/bin/sudo', 'systemctl' => '/bin/systemctl', 'flock' => '/usr/bin/flock', 'ffmpeg' => '/x/ffmpeg', 'gsm' => '/x/gsm'],
	'asterisk' => 'Asterisk 18.20.0', 'patch_state' => 'ok', 'globals_state' => 'ok', 'activation' => 'ok', 'service_active' => true,
	'writable' => ['/var/lib/asterisk-recording-uploader' => true], 'disk_free_mb' => 50000,
];
$report = DependencyCheck::evaluate($healthy);
if (!$report['ok'] || $report['blocking'] !== 0 || $report['warnings'] !== 0) { $fail('healthy host should be clean: ' . json_encode($report)); }

// Missing callrecording: blocking, one-click installable, coded.
$env = $healthy;
$env['modules']['callrecording'] = ['status' => 'missing', 'version' => ''];
$r = DependencyCheck::evaluate($env);
$cr = $row($r, 'module_callrecording');
if ($r['ok'] || $cr['status'] !== 'fail' || $cr['install_module'] !== 'callrecording' || $cr['code'] !== 'SS-DEP-1001') { $fail('missing callrecording: ' . json_encode($cr)); }

// Optional voicemail missing: warning only, still installable.
$env = $healthy;
$env['modules']['voicemail'] = ['status' => 'disabled', 'version' => '16.0.2'];
$r = DependencyCheck::evaluate($env);
if (!$r['ok'] || $r['warnings'] !== 1 || $row($r, 'module_voicemail')['status'] !== 'warn') { $fail('optional module should only warn'); }

// Old PHP on the CLI (FreePBX 15 default) and a FreePBX 15.0.17 that must not be read as 17.
$env = $healthy;
$env['php_cli'] = '5.6.40';
$env['freepbx_version'] = '15.0.17';
$r = DependencyCheck::evaluate($env);
if ($row($r, 'php_cli')['status'] !== 'fail' || $row($r, 'freepbx')['status'] !== 'ok') { $fail('php_cli / freepbx 15 handling'); }
$env['freepbx_version'] = '14.0.13';
if ($row(DependencyCheck::evaluate($env), 'freepbx')['status'] !== 'fail') { $fail('FreePBX 14 must be refused'); }

// Patch drift and outdated globals are blocking and point at the activation step.
$env = $healthy;
$env['patch_state'] = 'drift';
$env['globals_state'] = 'outdated';
$r = DependencyCheck::evaluate($env);
if ($row($r, 'patch')['code'] !== 'SS-HOOK-1005' || $row($r, 'globals')['status'] !== 'fail' || $r['blocking'] < 2) { $fail('drift handling'); }

// Only allow-listed modules are installable, and every code used exists in the catalog.
foreach (DependencyCheck::evaluate(array_merge($healthy, ['modules' => [], 'cli_extensions' => [], 'web_extensions' => [], 'binaries' => [], 'patch_state' => 'drift', 'globals_state' => 'outdated', 'activation' => 'pending', 'service_active' => false, 'writable' => ['/x' => false], 'disk_free_mb' => 10]))['rows'] as $r) {
	if ($r['install_module'] !== null && !in_array($r['install_module'], DependencyCheck::INSTALLABLE_MODULES, true)) { $fail("non-allowlisted install {$r['install_module']}"); }
	if ($r['code'] !== '' && !ErrorCatalog::exists($r['code'])) { $fail("unknown code {$r['code']} in {$r['id']}"); }
	if (!in_array($r['status'], ['ok', 'warn', 'fail'], true)) { $fail('bad status'); }
}
echo "Dependency check passed.\n";
