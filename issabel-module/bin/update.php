#!/usr/bin/env php
<?php
require __DIR__ . '/../engine/autoload.php';
use Engine\IssabelSettings;
use Engine\ModuleUpdate;
if (PHP_SAPI !== 'cli' || posix_geteuid() !== 0 || !preg_match('/^[a-f0-9]{32}$/', $argv[1] ?? '')) { exit(2); }
$job = $argv[1];
$root = '/var/lib/sedasanj-issabel-updates';
if (!is_dir($root)) { mkdir($root, 0755, true); }
$lock = fopen($root . '/lock', 'c');
if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) { exit(1); }
$work = $root . '/' . $job;
if (file_exists($work)) { exit(1); }
mkdir($work, 0700);
$statusPath = '/var/lib/asterisk-recording-uploader/update-status.json';
function sj_status(string $state, string $code = ''): void {
    global $statusPath;
    IssabelSettings::atomic($statusPath, json_encode(['state' => $state, 'code' => $code]), 0644);
}
function sj_update_report(string $state): void {
    global $host, $m, $offer;
    try {
        $uuid = trim((string) file_get_contents('/var/lib/asterisk-recording-uploader/host_uuid'));
        if (strlen($uuid) < 8 || !isset($m['version'], $host['version'])) { return; }
        Engine\Uploader::postJson(Engine\Config::load(), 'module/update-report', [
            'product' => 'issabel-recuploader', 'host_uuid' => $uuid,
            'release_id' => $offer['id'] ?? null, 'from_version' => $host['version'],
            'to_version' => $m['version'], 'status' => $state,
            'message' => $state === 'failed' ? 'SS-UPD-1010: Open the Issabel update status and health checks.' : null,
        ]);
    } catch (Throwable $exception) { /* Local status is retained when the API is unreachable. */ }
}
function sj_update_cleanup(string $path): void {
    if (is_link($path) || !is_dir($path)) { if (file_exists($path) || is_link($path)) { unlink($path); } return; }
    foreach (new DirectoryIterator($path) as $entry) { if (!$entry->isDot()) { sj_update_cleanup($entry->getPathname()); } }
    rmdir($path);
}
$exitCode = 0;
try {
    sj_status('verify');
    $host = json_decode((string) file_get_contents('/etc/sedasanj-recuploader-update/host.json'), true);
    $spool = '/var/spool/asterisk-recording-uploader/updates/' . $job;
    $request = file_get_contents($spool . '/job.json', false, null, 0, 65537);
    if ($request === false || strlen($request) > 65536) { throw new RuntimeException('SS-UPD-1010'); }
    $offer = json_decode($request, true);
    $from = fopen($spool . '/release.tgz', 'rb'); $to = fopen($work . '/release.tgz', 'xb');
    if (!$from || !$to) { throw new RuntimeException('SS-UPD-1010'); }
    stream_copy_to_stream($from, $to, ModuleUpdate::MAX_ARTIFACT_BYTES + 1); fclose($from); fclose($to);
    if (filesize($work . '/release.tgz') > ModuleUpdate::MAX_ARTIFACT_BYTES) { throw new RuntimeException('SS-UPD-1010'); }
    $manifest = (string) ($offer['manifest'] ?? '');
    $m = json_decode($manifest, true);
    if (!is_array($m) || ($m['product'] ?? '') !== 'issabel-recuploader' || ($m['rawname'] ?? '') !== 'recuploader'
        || ($m['archive_format'] ?? '') !== 'tgz' || !ModuleUpdate::isVersion($m['version'] ?? '')
        || !isset($m['min_issabel_major'], $m['max_issabel_major'], $m['min_php_version'])
        || (int) $host['issabel_version'] < $m['min_issabel_major'] || (int) $host['issabel_version'] > $m['max_issabel_major']
        || version_compare(PHP_VERSION, $m['min_php_version'], '<')
        || version_compare($m['version'], $host['version'], '<=')
        || (!empty($m['min_from_version']) && version_compare($host['version'], $m['min_from_version'], '<'))
        || !in_array($m['channel'] ?? '', ['beta', 'stable'], true) || strtotime($m['expires_at'] ?? '') < time()
        || !strtotime($m['issued_at'] ?? '') || strtotime($m['issued_at']) > time() + 600
        || strlen($manifest) > 8192) { throw new RuntimeException('SS-UPD-1010'); }
    $digest = hash_file('sha256', $work . '/release.tgz');
    $verified = false; $manifestVerified = false;
    foreach (ModuleUpdate::parsePublicKeys((string) file_get_contents('/etc/sedasanj-recuploader-update/release-signing.pub')) as $key) {
        $verified = $verified || ModuleUpdate::verifySignature($digest, (string) ($offer['signature'] ?? ''), $key);
        $signature = base64_decode($offer['manifest_signature'] ?? '', true);
        $manifestVerified = $manifestVerified || ($signature !== false && strlen($signature) === 64 && sodium_crypto_sign_verify_detached($signature, "sedasanj-module-manifest-v1\n" . $manifest, $key));
    }
    if (!$verified || !$manifestVerified || !hash_equals($m['sha256'] ?? '', $digest) || ($m['size'] ?? -1) !== filesize($work . '/release.tgz')) { throw new RuntimeException('SS-UPD-1010'); }
    sj_status('extract');
    Engine\TarArchive::extract($work . '/release.tgz', $work . '/extract');
    $source = $work . '/extract/recuploader';
    $xml = simplexml_load_file($source . '/module.xml');
    if ((string) $xml->product !== 'issabel-recuploader' || (string) $xml->version !== $m['version'] || (string) $xml->rawname !== 'recuploader') { throw new RuntimeException('SS-UPD-1010'); }
    sj_update_report('started');
    sj_status('install');
    // Activation handles a verified backup and rollback. Use the protected installed provisioner.
    $command = escapeshellarg($host['system_php']) . ' ' . escapeshellarg(__DIR__ . '/../lib/bridge.php') . ' inventory | '
        . escapeshellarg(PHP_BINARY) . ' ' . escapeshellarg(__DIR__ . '/provision.php') . ' ' . escapeshellarg($source) . ' ' . escapeshellarg($host['php_cli']);
    passthru('/bin/bash -o pipefail -c ' . escapeshellarg($command), $exit);
    if ($exit !== 0) { throw new RuntimeException('SS-UPD-1010'); }
    sj_status('succeeded'); sj_update_report('succeeded');
} catch (Throwable $exception) {
    sj_status('failed', 'SS-UPD-1010'); sj_update_report('failed'); $exitCode = 1;
} finally { sj_update_cleanup($work); flock($lock, LOCK_UN); fclose($lock); }
exit($exitCode);
