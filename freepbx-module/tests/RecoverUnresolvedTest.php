<?php
// failed/ recordings whose destination was a dialplan label are re-queued only when the
// numbers can be resolved (here: from the inbound DID), then delivered by the normal worker.
require __DIR__ . '/../engine/autoload.php';

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$root = sys_get_temp_dir() . '/aru-recover-' . getmypid();
foreach (['pending', 'failed', 'state', 'log', 'uploaded', 'monitor'] as $d) { @mkdir("$root/$d", 0755, true); }
file_put_contents("$root/router.php", '<?php http_response_code(200); echo json_encode(["call_id"=>"c1"]);');
$port = 21000 + (getmypid() % 1000);
$server = proc_open([PHP_BINARY, '-S', "127.0.0.1:$port", "$root/router.php"], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
for ($i = 0; $i < 50; $i++) { $s = @fsockopen('127.0.0.1', $port); if ($s) { fclose($s); break; } usleep(100000); }

$ini = "$root/config.ini";
file_put_contents($ini, "[general]\nendpoint = http://127.0.0.1:$port/calls\napi_key = sk_live_recoverkey123\n"
    . "verify_tls = false\ntimeout_seconds = 10\nimmediate_retries = 0\n[upload]\nformat = wav\n"
    . "[post_upload]\non_success = keep\nmove_dir = $root/uploaded\n[archive]\nformat = wav\n"
    . "[watcher]\nwatch_dir = $root/monitor\nstate_file = $root/state/w.json\n"
    . "[queue]\nspool_dir = $root/pending\nfailed_dir = $root/failed\n"
    . "[state]\nstate_file = $root/state/s.json\n"
    . "[logging]\nlog_file = $root/log/u.log\nlog_level = DEBUG\nuse_syslog = false\n");

function failedJob(string $root, string $uid, array $metadata, string $code): string
{
    $audio = "$root/failed/stereo_in-20261029-$uid.wav.gz";
    file_put_contents($audio, str_repeat('x', 3000));
    $manifest = "$root/failed/" . hash('sha256', $uid) . '.json';
    file_put_contents($manifest, json_encode([
        'metadata' => $metadata,
        'error_code' => $code,
        'files' => [$audio],
    ]));
    return $audio;
}

$script = escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/../engine/bin/recover-unresolved.php')
    . ' --config=' . escapeshellarg($ini) . ' --older-than=0';

// 1. Recoverable: the inbound DID resolves the dialplan label.
$uid = '1730000000.41';
$audio = failedJob($root, $uid, [
    'uniqueid' => $uid, 'src' => '09351234567', 'dst' => 'recordcheck', 'from_did' => '02112345678',
    'dst_label' => 'recordcheck', 'direction' => 'inbound',
    'start_time' => '2026-10-29T10:00:00Z', 'ended_at' => '2026-10-29T10:01:00Z',
    'source_filename' => "stereo_in-20261029-$uid.wav",
], 'SS-UPL-0422');

exec($script . ' --dry-run 2>&1', $dryOut, $dryCode);
if ($dryCode !== 0 || !is_file($audio) || glob("$root/pending/*")) { $fail('dry run moved a recording: ' . implode("\n", $dryOut)); }

exec($script . ' 2>&1', $out, $code);
clearstatcache();
if ($code !== 0) { $fail("recovery failed (exit $code): " . implode("\n", $out)); }
if (is_file($audio) || !glob("$root/pending/*")) {
    $fail('the recovered recording was not moved to pending: ' . implode("\n", $out));
}
if (glob("$root/failed/*.json")) { $fail('the manifest was not removed after a successful requeue'); }
$sidecar = glob("$root/pending/*.metadata.json");
if (!$sidecar || strpos((string) file_get_contents($sidecar[0]), '02112345678') === false) {
    $fail('the resolved destination was not written to the sidecar');
}

// 2. The normal worker delivers it.
$cfg = Engine\Config::load($ini);
$log = new Engine\Logger($cfg, 'test');
Engine\QueueWorker::tick($cfg, $log);
if (glob("$root/pending/*")) { $fail('the re-queued recording was not delivered'); }

// 3. Unresolvable: no CDR, no DID -> stays in failed/ and the command reports it.
$uid2 = '1730000000.42';
$audio2 = failedJob($root, $uid2, [
    'uniqueid' => $uid2, 'src' => '09351234567', 'dst' => 'recordcheck',
    'dst_label' => 'recordcheck', 'direction' => 'inbound',
    'start_time' => '2026-10-29T10:00:00Z', 'ended_at' => '2026-10-29T10:01:00Z',
    'source_filename' => "stereo_in-20261029-$uid2.wav",
], 'SS-UPL-0422');
exec($script . ' 2>&1', $out2, $code2);
clearstatcache();
if ($code2 !== 1) { $fail("unresolved recording should exit 1, got $code2: " . implode("\n", $out2)); }
if (!is_file($audio2)) { $fail('an unresolved recording was moved out of failed/'); }
if (strpos((string) file_get_contents("$root/log/u.log"), 'SS-SWP-1001') === false) {
    $fail('the unresolved recording was not logged with SS-SWP-1001');
}

proc_terminate($server);
exec('rm -rf ' . escapeshellarg($root));
echo "Recover unresolved passed.\n";
