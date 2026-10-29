<?php
// Uploader HTTP classification against a local stub server (php -S): which responses pause the
// queue, which fail a recording for good, which are retried, and that secrets never leak.
require __DIR__ . '/../engine/autoload.php';

use Engine\Config;
use Engine\ErrorCatalog;
use Engine\UploadError;
use Engine\Uploader;

$fail = function ($m) { fwrite(STDERR, "FAIL: $m\n"); exit(1); };
$dir = sys_get_temp_dir() . '/aru-uploader-' . getmypid();
@mkdir($dir);

// Stub: /<status>/<server-code>/calls answers with that status and an ingest-style error body.
file_put_contents("$dir/router.php", <<<'PHP'
<?php
$parts = explode('/', trim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH), '/'));
$status = (int) ($parts[0] ?? 200);
$code = $parts[1] ?? '-';
file_put_contents(dirname(__FILE__) . '/last.json', json_encode(['type' => $_SERVER['CONTENT_TYPE'] ?? '', 'len' => (int) ($_SERVER['CONTENT_LENGTH'] ?? 0), 'files' => array_keys($_FILES), 'uid' => $_POST['asterisk_uniqueid'] ?? null]));
http_response_code($status);
header('X-Request-ID: stub-' . $status);
if ($status >= 200 && $status < 300) {
	echo json_encode(['call_id' => 'x', 'replayed' => $code === 'replayed']);
} elseif ($code === 'html') {
	echo '<html>proxy error</html>';
} elseif ($code !== '-') {
	echo json_encode(['error' => ['code' => $code, 'message' => 'stub ' . $code . ' key sk_live_LEAKME123456', 'request_id' => 'req-' . $status]]);
}
PHP);
$port = 18000 + (getmypid() % 1000);
$server = proc_open([PHP_BINARY, '-S', "127.0.0.1:$port", "$dir/router.php"], [1 => ['file', '/dev/null', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
for ($i = 0; $i < 50; $i++) {
	$sock = @fsockopen('127.0.0.1', $port);
	if ($sock) { fclose($sock); break; }
	usleep(100000);
}

$audio = "$dir/stereo_1730000000.1.wav";
file_put_contents($audio, str_repeat("\0", 2048));
$metadata = ['uniqueid' => '1730000000.1', 'src' => '1001', 'dst' => '1002',
	'started_at' => '2026-10-29T10:00:00Z', 'ended_at' => '2026-10-29T10:01:00Z'];
$base = Config::DEFAULTS;
$base['general']['api_key'] = 'sk_live_LEAKME123456';
$base['general']['timeout_seconds'] = 5;

$cases = [
	// path, retryable, credit, config, code
	['401/unauthorized', true, false, true, 'SS-UPL-0401'],
	['401/-', true, false, true, 'SS-UPL-0401'],
	['403/tenant_suspended', true, false, true, 'SS-UPL-0403'],
	['404/-', true, false, true, 'SS-UPL-0404'],
	['422/archive_password_invalid', true, false, true, 'SS-UPL-0422'],
	['415/unsupported_archive', true, false, true, 'SS-UPL-0415'],
	['402/insufficient_credit', true, true, false, 'SS-UPL-0402'],
	['413/archive_too_large', false, false, false, 'SS-UPL-0413'],
	['415/unsupported_audio', false, false, false, 'SS-UPL-0415'],
	['422/invalid_request', false, false, false, 'SS-UPL-0422'],
	['429/rate_limited', true, false, false, 'SS-UPL-0429'],
	['500/internal', true, false, false, 'SS-UPL-0500'],
	['502/html', true, false, false, 'SS-UPL-0500'],
	['418/-', true, false, false, 'SS-UPL-0599'],
];
foreach ($cases as [$path, $retryable, $credit, $config, $code]) {
	$cfg = $base;
	$cfg['general']['endpoint'] = "http://127.0.0.1:$port/$path/calls";
	try {
		Uploader::uploadFile($cfg, $audio, $metadata);
		$fail("$path: expected failure");
	} catch (UploadError $e) {
		if ($e->retryable !== $retryable || $e->creditBlocked !== $credit || $e->configBlocked !== $config || $e->errorCode !== $code) {
			$fail("$path: got retryable=" . var_export($e->retryable, true) . ' credit=' . var_export($e->creditBlocked, true)
				. ' config=' . var_export($e->configBlocked, true) . " code={$e->errorCode}");
		}
		if (strpos($e->getMessage(), 'LEAKME') !== false) { $fail("$path: API key leaked into the error message"); }
		if (!ErrorCatalog::exists($e->errorCode)) { $fail("$path: uncatalogued code {$e->errorCode}"); }
	}
}

// Success and server-side replay.
$cfg = $base;
$cfg['general']['endpoint'] = "http://127.0.0.1:$port/200/-/calls";
$ok = Uploader::uploadFile($cfg, $audio, $metadata);
if ($ok['replayed'] !== false || $ok['status_code'] !== 200) { $fail('plain success'); }
$seen = json_decode((string) file_get_contents("$dir/last.json"), true);
if (strpos($seen['type'], 'multipart/form-data') !== 0 || $seen['len'] < 2048 || $seen['files'] !== ['file'] || $seen['uid'] !== '1730000000.1') {
	$fail('upload body is not the expected multipart request: ' . json_encode($seen));
}
$cfg['general']['endpoint'] = "http://127.0.0.1:$port/200/replayed/calls";
if (Uploader::uploadFile($cfg, $audio, $metadata)['replayed'] !== true) { $fail('replay not surfaced'); }

// Server request id captured from the response error body.
$cfg['general']['endpoint'] = "http://127.0.0.1:$port/500/internal/calls";
try { Uploader::uploadFile($cfg, $audio, $metadata); } catch (UploadError $e) {
	if (($e->context['server_request_id'] ?? '') !== 'req-500') { $fail('server request id missing: ' . json_encode($e->context)); }
}

// Transport failure: closed port -> coded, retryable network error.
$cfg['general']['endpoint'] = 'http://127.0.0.1:9/200/-/calls';
try { Uploader::uploadFile($cfg, $audio, $metadata); $fail('refused connection succeeded'); } catch (UploadError $e) {
	if (!$e->retryable || $e->statusCode !== null || !in_array($e->errorCode, ['SS-UPL-2003', 'SS-UPL-2001'], true)) { $fail("network: {$e->errorCode}"); }
}

// Voicemail endpoint cannot be derived from an endpoint that does not end in /calls.
$cfg['general']['endpoint'] = "http://127.0.0.1:$port/200/-/ingest";
$vm = ['_voicemail' => true, 'uniqueid' => 'vm1', 'mailbox' => '1001', 'context' => 'default', 'folder' => 'INBOX', 'started_at' => '2026-10-29T10:00:00Z'];
try { Uploader::uploadFile($cfg, $audio, $vm); $fail('voicemail posted to a guessed endpoint'); } catch (UploadError $e) {
	if ($e->errorCode !== 'SS-CFG-1004' || $e->retryable) { $fail("voicemail endpoint: {$e->errorCode}"); }
}

proc_terminate($server);
array_map('unlink', glob("$dir/*"));
@rmdir($dir);
echo "Uploader HTTP classification passed.\n";
