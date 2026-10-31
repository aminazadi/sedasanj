#!/usr/bin/env php
<?php
require __DIR__ . '/../engine/autoload.php';
require __DIR__ . '/../lib/Process.php';
use Engine\Config;
use Engine\IssabelSettings;
use Engine\ModuleUpdate;

function sj_http(array $cfg, string $url, ?array $body = null): array {
    if (parse_url($url, PHP_URL_SCHEME) !== 'https') { throw new RuntimeException('SS-CFG-1004'); }
    $curl = curl_init($url);
    curl_setopt_array($curl, [CURLOPT_RETURNTRANSFER => true, CURLOPT_FOLLOWLOCATION => false,
        CURLOPT_CONNECTTIMEOUT => 5, CURLOPT_TIMEOUT => 30, CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
        CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_HTTPHEADER => array_filter(['Authorization: Bearer ' . $cfg['general']['api_key'], 'Content-Type: application/json', $cfg['general']['archive_password'] !== '' ? 'X-CBI-Archive-Password: ' . $cfg['general']['archive_password'] : null]),
        CURLOPT_WRITEFUNCTION => static function ($ch, $chunk) use (&$response) {
            $response = ($response ?? '') . $chunk;
            return strlen($response) <= 1048576 ? strlen($chunk) : 0;
        }]);
    if ($body !== null) { curl_setopt($curl, CURLOPT_POST, true); curl_setopt($curl, CURLOPT_POSTFIELDS, json_encode($body)); }
    $response = ''; $result = curl_exec($curl); $status = curl_getinfo($curl, CURLINFO_HTTP_CODE); curl_close($curl);
    if ($result === false || $status < 200 || $status >= 300) { throw new RuntimeException('SS-UPL-2001'); }
    $decoded = json_decode($response, true);
    if (!is_array($decoded)) { throw new RuntimeException('SS-UPL-2001'); }
    return $decoded;
}
function sj_update_query(array $host): array {
    $uuid = @file_get_contents('/var/lib/asterisk-recording-uploader/host_uuid');
    if (!$uuid) { $uuid = bin2hex(random_bytes(16)); IssabelSettings::atomic('/var/lib/asterisk-recording-uploader/host_uuid', $uuid); }
    return ['product' => 'issabel-recuploader', 'current' => $host['version'], 'host_uuid' => trim($uuid),
        'issabel' => $host['issabel_version'], 'framework' => $host['framework_version'], 'php_web' => $host['php_web'],
        'php' => PHP_VERSION, 'hostname' => gethostname(), 'channel' => 'beta'];
}
function sj_public_settings(array $cfg): array {
    $cfg['general']['api_key'] = ''; $cfg['general']['api_key_b64'] = '';
    $cfg['general']['archive_password'] = ''; $cfg['general']['archive_password_b64'] = '';
    return $cfg;
}
try {
    if (PHP_SAPI !== 'cli') { exit(2); }
    $json = stream_get_contents(STDIN, 65537);
    if (strlen($json) > 65536) { throw new RuntimeException('SS-CFG-1003'); }
    $request = json_decode($json, true);
    $op = $request['op'] ?? '';
    $cfg = is_file(Config::DEFAULT_CONFIG_PATH) ? Config::load() : IssabelSettings::defaults();
    $host = json_decode((string) @file_get_contents('/etc/sedasanj-recuploader-update/host.json'), true) ?: [];
    if (isset($request['php_web']) && preg_match('/^[0-9]+\.[0-9]+\.[0-9]+/', $request['php_web'])) { $host['php_web'] = $request['php_web']; }
    switch ($op) {
    case 'settings':
        if ($cfg['general']['api_key'] !== '' && $host) { try { sj_http($cfg, ModuleUpdate::updatesUrl($cfg['general']['endpoint'], sj_update_query($host))); } catch (Throwable $exception) {} }
        $data = sj_public_settings($cfg); break;
    case 'save':
        $cfg = IssabelSettings::validate($request['settings'] ?? [], $cfg);
        if ($cfg['missed_calls']['enabled'] && empty(Engine\CdrSource::connect()->diagnostics()['available'])) { throw new RuntimeException('SS-CDR-1002'); }
        $old = (string) file_get_contents(Config::DEFAULT_CONFIG_PATH);
        IssabelSettings::write($cfg, Config::DEFAULT_CONFIG_PATH);
        try { SedaSanjProcess::run(['sudo', '-n', '/usr/local/sbin/sedasanj-issabel-control', 'restart'], '', 20); }
        catch (Throwable $exception) { IssabelSettings::atomic(Config::DEFAULT_CONFIG_PATH, $old); throw new RuntimeException('SS-SVC-1001'); }
        $data = sj_public_settings($cfg); break;
    case 'import':
        $doc = json_decode($request['profile'] ?? '', true);
        if (!is_array($doc) || ($doc['schema'] ?? '') !== 'sedasanj.issabel.recuploader.config' || ($doc['target'] ?? '') !== 'issabel-module') { throw new RuntimeException('SS-CFG-1003'); }
        $doc['schema'] = Engine\ConfigProfile::SCHEMA; $doc['target'] = 'freepbx-module';
        Engine\ConfigProfile::parse(json_encode($doc));
        $settings = $doc['settings'];
        $settings['watcher']['watch_dir'] = IssabelSettings::defaults()['watcher']['watch_dir'];
        $settings['state']['exclude_patterns'] = $settings['watcher']['exclude_patterns']; unset($settings['watcher']['exclude_patterns']);
        $cfg = IssabelSettings::validate($settings, $cfg);
        $data = sj_public_settings($cfg);
        // Keep the preview server-side; a second explicit apply action persists it.
        IssabelSettings::atomic('/var/lib/asterisk-recording-uploader/import-preview.json', json_encode($cfg), 0600);
        break;
    case 'applyimport':
        $preview = json_decode((string) file_get_contents('/var/lib/asterisk-recording-uploader/import-preview.json'), true);
        if (!is_array($preview)) { throw new RuntimeException('SS-CFG-1003'); }
        $cfg = IssabelSettings::validate($preview, $cfg);
        $validation = sj_http($cfg, ModuleUpdate::endpointFor($cfg['general']['endpoint'], '/config/validate'), []);
        if (($validation['archive_format'] ?? '') !== $cfg['upload']['format'] || empty($validation['archive_password_valid'])) { throw new RuntimeException('SS-CFG-1003'); }
        $old = (string) file_get_contents(Config::DEFAULT_CONFIG_PATH);
        IssabelSettings::write($cfg, Config::DEFAULT_CONFIG_PATH);
        try { SedaSanjProcess::run(['sudo', '-n', '/usr/local/sbin/sedasanj-issabel-control', 'restart'], '', 20); }
        catch (Throwable $exception) { IssabelSettings::atomic(Config::DEFAULT_CONFIG_PATH, $old); throw new RuntimeException('SS-SVC-1001'); }
        unlink('/var/lib/asterisk-recording-uploader/import-preview.json'); $data = sj_public_settings($cfg); break;
    case 'health':
        $checks = [];
        foreach (['curl', 'pdo_mysql', 'pdo_sqlite', 'zlib', 'ctype', 'sodium'] as $extension) { $checks[$extension] = extension_loaded($extension); }
        $checks['activation'] = is_file('/etc/sedasanj-recuploader-update/issabel-active');
        $checks['recording_hook'] = !is_file('/var/lib/asterisk-recording-uploader/issabel-hook-error');
        $checks['service'] = trim((string) shell_exec('systemctl is-active asterisk-recording-uploader.service 2>/dev/null')) === 'active';
        $cdr = null; try { $cdr = Engine\CdrSource::connect()->diagnostics(); } catch (Throwable $exception) { $cdr = ['available' => false, 'code' => 'SS-CDR-1003']; }
        $data = ['host' => $host, 'php_cli' => PHP_VERSION, 'checks' => $checks, 'cdr' => $cdr,
            'selinux' => trim((string) shell_exec('getenforce 2>/dev/null')),
            'systemd' => strtok((string) shell_exec('systemctl --version 2>/dev/null'), "\n"),
            'action' => 'پس از رفع موارد ناموفق، فعال‌سازی را اجرا و یک تماس آزمایشی ثبت کنید.']; break;
    case 'logs':
        $path = '/var/log/asterisk-recording-uploader/uploader.log';
        $handle = @fopen($path, 'rb'); $text = '';
        if ($handle) { fseek($handle, max(0, filesize($path) - 65536)); $text = stream_get_contents($handle); fclose($handle); }
        $level = $request['level'] ?? 'ALL';
        $ranks = ['ALL' => 0, 'DEBUG' => 10, 'INFO' => 20, 'WARNING' => 30, 'ERROR' => 40];
        if (!isset($ranks[$level])) { throw new RuntimeException('SS-CFG-1003'); }
        $lines = array_filter(explode("\n", $text), static function ($line) use ($ranks, $level) {
            return $level === 'ALL' || (preg_match('/\]\\s+(DEBUG|INFO|WARNING|ERROR)\\s/', $line, $m) && $ranks[$m[1]] >= $ranks[$level]);
        });
        $data = ['text' => Engine\Logger::redact(implode("\n", array_slice($lines, -150)), [$cfg['general']['api_key'], $cfg['general']['archive_password']])]; break;
    case 'queue':
        $jobs = array_slice(Engine\Queue::create($cfg)->dueJobs(), 0, 100);
        $data = array_map(static function ($job) { return ['job_id' => $job['job_id'], 'attempts' => $job['attempts'] ?? 0, 'next_attempt' => $job['next_attempt'] ?? null]; }, $jobs); break;
    case 'requeue':
        $text = SedaSanjProcess::run([PHP_BINARY, __DIR__ . '/../engine/bin/requeue-failed.php'], '', 30);
        $data = ['text' => Engine\Logger::redact($text)]; break;
    case 'extensions':
    case 'sync':
        $rows = json_decode(SedaSanjProcess::run(['/usr/bin/php', __DIR__ . '/../lib/bridge.php', 'extensions'], '', 10), true);
        $data = Engine\ExtensionSync::buildPayload($rows ?: []);
        if ($op === 'sync') { $data = sj_http($cfg, ModuleUpdate::extensionsSyncUrl($cfg['general']['endpoint']), $data); }
        break;
    case 'models':
        $data = sj_http($cfg, ModuleUpdate::endpointFor($cfg['general']['endpoint'], '/config/validate'), ['upload_format' => $cfg['upload']['format']]); break;
    case 'checkupdate':
        $data = sj_http($cfg, ModuleUpdate::updatesUrl($cfg['general']['endpoint'], sj_update_query($host))); break;
    case 'update':
        $check = sj_http($cfg, ModuleUpdate::updatesUrl($cfg['general']['endpoint'], sj_update_query($host)));
        $offer = $check['latest'] ?? null;
        if (!$offer || !ModuleUpdate::isReleaseId($offer['id'] ?? '')) { throw new RuntimeException('SS-UPD-1010'); }
        $job = bin2hex(random_bytes(16)); $dir = '/var/spool/asterisk-recording-uploader/updates/' . $job;
        mkdir($dir, 0750, true); IssabelSettings::atomic($dir . '/job.json', json_encode($offer));
        $file = fopen($dir . '/release.tgz', 'xb'); $bytes = 0;
        $url = ModuleUpdate::downloadUrl($cfg['general']['endpoint'], $offer['id']) . '?product=issabel-recuploader';
        $curl = curl_init($url);
        curl_setopt_array($curl, [CURLOPT_FOLLOWLOCATION => false, CURLOPT_TIMEOUT => 300, CURLOPT_PROTOCOLS => CURLPROTO_HTTPS,
            CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $cfg['general']['api_key']],
            CURLOPT_WRITEFUNCTION => static function ($ch, $chunk) use ($file, &$bytes) { $bytes += strlen($chunk); return $bytes <= ModuleUpdate::MAX_ARTIFACT_BYTES ? fwrite($file, $chunk) : 0; }]);
        $ok = curl_exec($curl); $status = curl_getinfo($curl, CURLINFO_HTTP_CODE); curl_close($curl); fclose($file);
        if ($ok === false || $status !== 200) { throw new RuntimeException('SS-UPD-1010'); }
        IssabelSettings::atomic('/var/lib/asterisk-recording-uploader/update-status.json', json_encode(['state' => 'queued', 'job_id' => $job]), 0644);
        SedaSanjProcess::run(['sudo', '-n', '/usr/local/sbin/sedasanj-issabel-control', 'update', $job], '', 15);
        $data = ['job_id' => $job]; break;
    case 'updatestatus':
        $data = json_decode((string) @file_get_contents('/var/lib/asterisk-recording-uploader/update-status.json'), true) ?: ['state' => 'idle']; break;
    case 'service':
        $action = $request['action'] ?? '';
        if (!in_array($action, ['start', 'stop', 'restart'], true)) { throw new RuntimeException('SS-CFG-1003'); }
        SedaSanjProcess::run(['sudo', '-n', '/usr/local/sbin/sedasanj-issabel-control', $action], '', 20); $data = ['done' => true]; break;
    case 'support':
        require_once __DIR__ . '/../engine/bin/doctor.php';
        $data = doctor_run($cfg, false); break;
    default: throw new RuntimeException('SS-CFG-1003');
    }
    echo json_encode(['ok' => true, 'data' => $data], JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
} catch (Throwable $exception) {
    $code = preg_match('/SS-[A-Z]+-[0-9]{4}/', $exception->getMessage(), $match) ? $match[0] : 'SS-SYS-1011';
    echo json_encode(['ok' => false, 'code' => $code, 'message' => 'بررسی سلامت و راهنمای خطا را باز کنید، مورد ناموفق را اصلاح و دوباره تلاش کنید.', 'help' => 'https://sedasanj.ir/help/errors/' . $code], JSON_UNESCAPED_UNICODE);
}
