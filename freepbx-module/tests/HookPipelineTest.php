<?php
// End to end through bin/mix-stereo.php -> bin/uploader.php against a stub server:
// stereo merge + upload, mono fallback when a leg is corrupt, and pausing (not failing)
// the recording when the API key is rejected.
require __DIR__ . '/../engine/autoload.php';

use Engine\Audio\Wav;
use Engine\Audio\WavFile;

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = sys_get_temp_dir() . '/aru-hook-' . getmypid();
@mkdir($root, 0755, true);

file_put_contents("$root/router.php", <<<'PHP'
<?php
$parts = explode('/', trim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH), '/'));
$status = (int) ($parts[0] ?? 200);
file_put_contents(dirname(__FILE__) . '/hits.log', json_encode([
	'path' => $_SERVER['REQUEST_URI'], 'type' => $_SERVER['CONTENT_TYPE'] ?? '',
    'direction' => $_POST['direction'] ?? '',
	'uid' => preg_match('/name="asterisk_uniqueid"\r\n\r\n([^\r]+)/', (string) file_get_contents('php://input'), $m) ? $m[1] : ($_POST['asterisk_uniqueid'] ?? null),
]) . "\n", FILE_APPEND);
http_response_code($status);
if ($status === 401) { echo json_encode(['error' => ['code' => 'unauthorized', 'message' => 'bad key', 'retryable' => false]]); }
else { echo json_encode(['call_id' => 'c1']); }
PHP);
$port = 19000 + (getmypid() % 1000);
$server = proc_open([PHP_BINARY, '-S', "127.0.0.1:$port", "$root/router.php"], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
for ($i = 0; $i < 50; $i++) { $s = @fsockopen('127.0.0.1', $port); if ($s) { fclose($s); break; } usleep(100000); }

function writeConfig(string $root, int $port, string $path, string $archive = 'wav'): string
{
	foreach (['pending', 'failed', 'uploaded', 'state', 'log', 'monitor'] as $d) { @mkdir("$root/$d", 0755, true); }
	$ini = "$root/config.ini";
	file_put_contents($ini, <<<INI
[general]
endpoint = http://127.0.0.1:$port/$path/calls
api_key = sk_live_testkey123456
verify_tls = false
timeout_seconds = 10
immediate_retries = 0
[upload]
format = wav
[post_upload]
on_success = keep
move_dir = $root/uploaded
[archive]
format = $archive
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
	return $ini;
}

function leg(string $path, int $seconds = 1): void
{
	Wav::write($path, new WavFile(1, 8000, 16, str_repeat("\x10\x00", 8000 * $seconds)));
}

function run(string $root, string $ini, string $uid, bool $corruptLeg): array
{
	$dir = "$root/monitor/2026/10/29/";
	@mkdir($dir, 0755, true);
	$name = "out-1002-1001-20261029-100000-$uid";
	leg("{$dir}recv_$name.wav");
	leg("{$dir}trans_$name.wav");
	leg("{$dir}$name.wav");
	if ($corruptLeg) { file_put_contents("{$dir}recv_$name.wav", 'not a wav'); }
	putenv("ARU_CONFIG=$ini");
	$cmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/../engine/bin/mix-stereo.php')
		. ' ' . implode(' ', array_map('escapeshellarg', [$dir, $name, $uid, '1001', '1002', '', '1002', '']));
	exec($cmd . ' 2>&1', $out, $code);
	return [$code, implode("\n", $out), $dir, $name];
}

function runNormalizedFilename(string $root, string $ini, string $uid): array
{
    $dir = "$root/monitor/2026/10/29/";
    @mkdir($dir, 0755, true);
    $name = "out1002-1001-20261029-100000-$uid";
    leg("{$dir}recv_out-1002-1001-20261029-100000-$uid.wav");
    leg("{$dir}trans_out-1002-1001-20261029-100000-$uid.wav");
    leg("{$dir}$name.wav");
    putenv("ARU_CONFIG=$ini");
    $cmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/../engine/bin/mix-stereo.php')
        . ' ' . implode(' ', array_map('escapeshellarg', [$dir, $name, $uid, '1001', '1002', '', '1002', '']));
    exec($cmd . ' 2>&1', $out, $code);
    return [$code, implode("\n", $out), $dir, $name];
}

// A. healthy legs -> stereo upload, nothing left behind.
$ini = writeConfig($root, $port, '200/-');
[$code, $out, $dir, $name] = run($root, $ini, '1730000000.1', false);
if ($code !== 0) { $fail("A: exit $code: $out"); }
// on_success=keep leaves only the local archive copy (<name>.wav); legs, stereo and sidecars must be gone.
foreach (glob("$dir*") ?: [] as $left) { if (basename($left) !== "$name.wav") { $fail('A: left behind ' . basename($left)); } }
$hits = array_filter(explode("\n", (string) @file_get_contents("$root/hits.log")));
if (count($hits) !== 1 || strpos($hits[0], '"uid":"1730000000.1"') === false && strpos($hits[0], 'multipart/form-data') === false) { $fail('A: expected exactly one upload: ' . json_encode($hits)); }

// B. corrupt caller leg -> merge fails, mono mix is delivered, failure is logged with its code.
@unlink("$root/hits.log");
[$code, $out, $dir, $name] = run($root, $ini, '1730000000.2', true);
if ($code !== 0) { $fail("B: exit $code: $out"); }
if (strpos(file_get_contents("$root/log/uploader.log"), 'SS-HOOK-1003') === false) { $fail('B: merge failure not logged with SS-HOOK-1003'); }
if (count(array_filter(explode("\n", (string) @file_get_contents("$root/hits.log")))) !== 1) { $fail('B: mono fallback was not uploaded'); }
foreach (glob("{$dir}*.part") ?: [] as $p) { $fail('B: .part left behind'); }

// B2. Asterisk filename normalization removes hyphens only from the hook argument.
@unlink("$root/hits.log");
[$code, $out] = runNormalizedFilename($root, $ini, '1730000000.22');
if ($code !== 0) { $fail("B2: normalized filename failed: $out"); }
if (strpos((string) file_get_contents("$root/hits.log"), '"direction":"outbound"') === false) { $fail('B2: direction was lost after filename filtering'); }
if (count(array_filter(explode("\n", (string) @file_get_contents("$root/hits.log")))) !== 1) { $fail('B2: normalized filename was not uploaded'); }

// C. rejected key -> recording is kept and paused, never moved to failed/.
$ini = writeConfig($root, $port, '401/-');
@unlink("$root/hits.log");
[$code, $out, $dir, $name] = run($root, $ini, '1730000000.3', false);
if ($code !== 2) { $fail("C: expected spooled exit 2, got $code: $out"); }
if (glob("$root/failed/*")) { $fail('C: recording was moved to failed/ after a 401'); }
$cfg = Engine\Config::load($ini);
$jobs = Engine\Queue::create($cfg);
$job = null;
foreach ([Engine\Queue::jobId('', ['uniqueid' => '1730000000.3'])] as $id) { $job = $jobs->get($id); }
if ($job === null || $job['status'] !== 'blocked_config') { $fail('C: job not paused: ' . json_encode($job['status'] ?? null)); }
if (!is_file($job['filepath'])) { $fail('C: paused job lost its audio'); }
if (strpos(file_get_contents("$root/log/uploader.log"), 'SS-UPL-0401') === false) { $fail('C: 401 not logged with SS-UPL-0401'); }
if (strpos(file_get_contents("$root/log/uploader.log"), 'sk_live_testkey123456') !== false) { $fail('C: api key leaked into the log'); }

// D. local archive cannot be produced (unknown archive format) -> still delivered, warning logged.
$ini = writeConfig($root, $port, '200/-', 'zzz');
@unlink("$root/hits.log");
[$code, $out, $dir, $name] = run($root, $ini, '1730000000.4', false);
if ($code !== 0) { $fail("D: archive failure blocked the upload (exit $code): $out"); }
if (count(array_filter(explode("\n", (string) @file_get_contents("$root/hits.log")))) !== 1) { $fail('D: recording was not uploaded'); }
if (!preg_match('/WARNING|ERROR|INFO/', (string) file_get_contents("$root/log/uploader.log")) || strpos(file_get_contents("$root/log/uploader.log"), 'Local archive copy skipped') === false) {
	// the closure logs at DEBUG; the config sets log_level = DEBUG so it must be present
	$fail('D: archive failure not logged');
}

proc_terminate($server);
exec('rm -rf ' . escapeshellarg($root));
echo "Hook pipeline end-to-end passed.\n";
