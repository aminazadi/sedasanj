<?php
// A recording that failed for good (HTTP 413 from a stub) is re-queued by requeue-failed.php and then
// delivered by the normal queue worker once the endpoint accepts it.
require __DIR__ . '/../engine/autoload.php';

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = sys_get_temp_dir() . '/aru-requeue-' . getmypid();
foreach (['pending', 'failed', 'state', 'log', 'uploaded', 'monitor'] as $d) { @mkdir("$root/$d", 0755, true); }
file_put_contents("$root/router.php", '<?php $s=(int)explode("/",trim(parse_url($_SERVER["REQUEST_URI"],PHP_URL_PATH),"/"))[0]; http_response_code($s); echo json_encode($s>=400?["error"=>["code"=>"archive_too_large","message"=>"big"]]:["call_id"=>"c"]);');
$port = 20000 + (getmypid() % 1000);
$server = proc_open([PHP_BINARY, '-S', "127.0.0.1:$port", "$root/router.php"], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $p);
for ($i = 0; $i < 50; $i++) { $s = @fsockopen('127.0.0.1', $port); if ($s) { fclose($s); break; } usleep(100000); }
function ini(string $root, int $port, string $path): string {
	$f = "$root/config.ini";
	file_put_contents($f, "[general]\nendpoint = http://127.0.0.1:$port/$path/calls\napi_key = sk_live_requeuekey123\nverify_tls = false\ntimeout_seconds = 10\nimmediate_retries = 0\n[upload]\nformat = wav\n[post_upload]\non_success = keep\nmove_dir = $root/uploaded\n[archive]\nformat = wav\n[watcher]\nwatch_dir = $root/monitor\nstate_file = $root/state/w.json\n[queue]\nspool_dir = $root/pending\nfailed_dir = $root/failed\n[state]\nstate_file = $root/state/s.json\n[logging]\nlog_file = $root/log/u.log\nlog_level = DEBUG\nuse_syslog = false\n");
	return $f;
}
$audio = "$root/pending/stereo_1730000000.9.wav.gz";
file_put_contents($audio, str_repeat("x", 3000));
$meta = ['uniqueid' => '1730000000.9', 'src' => '1001', 'dst' => '1002', 'started_at' => '2026-10-29T10:00:00Z', 'ended_at' => '2026-10-29T10:01:00Z'];

// 1. permanent failure (413) -> failed/ with a manifest
$cfg = Engine\Config::load(ini($root, $port, '413'));
$log = new Engine\Logger($cfg, 'test');
$queue = Engine\Queue::create($cfg);
$id = $queue->spool($audio, null, $meta, 'x');
Engine\QueueWorker::processJob($cfg, $queue->get($id), $queue, $log);
$manifests = array_filter(glob("$root/failed/*.json") ?: [], function ($f) { return preg_match('/^[0-9a-f]{64}\.json$/', basename($f)); });
if (count($manifests) !== 1 || is_file($audio)) { $fail('setup: recording should be in failed/ with one manifest'); }

// 2. endpoint now accepts; dry run changes nothing, real run re-queues
ini($root, $port, '200');
$cmd = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/../engine/bin/requeue-failed.php') . ' --config=' . escapeshellarg("$root/config.ini");
exec($cmd . ' --dry-run 2>&1', $out, $code);
if ($code !== 0 || count(glob("$root/failed/*.json")) === 0 || is_file($audio)) { $fail('dry run must not move anything: ' . implode("\n", $out)); }
exec($cmd . ' --code=SS-UPL-9999 2>&1', $out2, $code);
if (is_file($audio)) { $fail('--code filter ignored'); }
exec($cmd . ' 2>&1', $out3, $code);
if ($code !== 0 || !is_file($audio) || array_filter(glob("$root/failed/*.json") ?: [], fn($f) => preg_match('/^[0-9a-f]{64}\.json$/', basename($f)))) {
	$fail('requeue did not move the recording back: ' . implode("\n", $out3));
}

// 3. the normal worker now delivers it
$cfg = Engine\Config::load("$root/config.ini");
$queue = Engine\Queue::create($cfg);
Engine\QueueWorker::tick($cfg, $log);
if (is_file($audio) || $queue->get($id) !== null) { $fail('queue worker did not deliver the re-queued recording'); }
proc_terminate($server);
exec('rm -rf ' . escapeshellarg($root));
echo "Requeue failed passed.\n";
