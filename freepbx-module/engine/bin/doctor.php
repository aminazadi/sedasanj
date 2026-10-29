#!/usr/bin/env php
<?php
/**
 * bin/doctor.php - self-test of the Seda Sanj engine on this PBX. Read-only except for a tiny
 * write test in the state directory. Prints a report (or JSON) with stable error codes, so a
 * support case can start from facts instead of guesses.
 *
 *   php doctor.php [--config=/etc/asterisk-recording-uploader/config.ini] [--json] [--no-network]
 *
 * Exit code: 0 all required checks passed, 1 a required check failed, 2 the config cannot be loaded.
 */

require_once __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\ErrorCatalog;
use Engine\Logger;

/** @return array<string,mixed> */
function doctor_run(array $cfg, bool $network): array
{
    $checks = [];
    $add = function (string $id, string $label, string $status, string $detail, string $code = '') use (&$checks) {
        $entry = $code !== '' ? ErrorCatalog::lookup($code) : null;
        $checks[] = ['id' => $id, 'label' => $label, 'status' => $status, 'detail' => Logger::redact($detail), 'code' => $code,
            'action' => $status === 'ok' ? '' : ($entry['action'] ?? ''), 'help_url' => $code !== '' ? ErrorCatalog::helpUrl($code) : ''];
    };

    $add('php', 'PHP CLI', version_compare(PHP_VERSION, '7.4.0', '>=') ? 'ok' : 'fail', PHP_VERSION . ' (' . PHP_SAPI . ')', 'SS-SYS-1001');
    foreach (['curl', 'zlib', 'json', 'pdo_sqlite', 'ctype'] as $ext) {
        $add("ext_$ext", "PHP extension $ext", extension_loaded($ext) ? 'ok' : 'fail', extension_loaded($ext) ? 'loaded' : 'missing', 'SS-SYS-1002');
    }
    foreach (['pcntl', 'sodium'] as $ext) {
        $add("ext_$ext", "PHP extension $ext (optional)", extension_loaded($ext) ? 'ok' : 'warn', extension_loaded($ext) ? 'loaded' : 'missing', 'SS-DEP-1003');
    }

    // Directories and disk
    $dirs = [
        'queue.spool_dir' => $cfg['queue']['spool_dir'],
        'queue.failed_dir' => $cfg['queue']['failed_dir'],
        'state directory' => dirname(Config::sqlitePath($cfg)),
        'log directory' => dirname((string) $cfg['logging']['log_file']),
    ];
    foreach ($dirs as $label => $dir) {
        $ok = is_dir($dir) && is_writable($dir);
        $add('dir_' . md5($dir), "Writable: $label", $ok ? 'ok' : 'fail', $dir . ($ok ? '' : ' is missing or not writable by ' . get_current_user()), 'SS-SYS-1007');
    }
    $free = @disk_free_space(is_dir($cfg['queue']['spool_dir']) ? $cfg['queue']['spool_dir'] : '/');
    if ($free !== false) {
        $mb = (int) ($free / 1048576);
        $add('disk', 'Free disk space (spool volume)', $mb < 500 ? 'fail' : ($mb < 2048 ? 'warn' : 'ok'), "$mb MB", 'SS-SYS-1005');
    }

    // Storage backend
    try {
        $store = Engine\StateStore::create($cfg);
        $usingSqlite = $store instanceof Engine\SqliteStateStore;
        $add('storage', 'State storage backend', $usingSqlite ? 'ok' : 'warn', $usingSqlite ? 'SQLite' : 'JSON fallback (pdo_sqlite unavailable or database not writable)', 'SS-SVC-1002');
    } catch (\Throwable $exc) {
        $add('storage', 'State storage backend', 'fail', $exc->getMessage(), 'SS-SVC-1002');
    }

    // Queue summary
    $summary = ['pending' => 0, 'blocked_credit' => 0, 'blocked_config' => 0, 'failed' => 0, 'oldest_pending_age_s' => 0];
    try {
        foreach (Engine\Queue::create($cfg)->dueJobs() as $job) {
            // dueJobs() only lists jobs whose retry time has come; enough for an "is it stuck" signal.
            $age = (int) max(0, time() - (int) ($job['created_epoch'] ?? time()));
            $summary['oldest_pending_age_s'] = max($summary['oldest_pending_age_s'], $age);
            $summary['pending']++;
        }
    } catch (\Throwable $exc) {
        // reported through the storage check above
    }
    foreach (glob(rtrim($cfg['queue']['failed_dir'], '/') . '/*.json') ?: [] as $manifest) {
        if (preg_match('/^[0-9a-f]{64}\.json$/', basename($manifest))) {
            $summary['failed']++;
        }
    }
    $add('queue', 'Retry queue', $summary['failed'] > 0 ? 'warn' : 'ok',
        "due now: {$summary['pending']}, failed manifests: {$summary['failed']}, oldest due job: {$summary['oldest_pending_age_s']}s", 'SS-QUE-1004');

    // Endpoint
    $endpoint = (string) $cfg['general']['endpoint'];
    $parts = parse_url($endpoint);
    if (!$parts || ($parts['scheme'] ?? '') !== 'https' || empty($parts['host'])) {
        $add('endpoint', 'Upload endpoint', 'fail', $endpoint === '' ? 'not configured' : $endpoint, 'SS-CFG-1004');
    } else {
        $add('endpoint', 'Upload endpoint', 'ok', $endpoint);
        if ($network) {
            $ip = gethostbyname($parts['host']);
            $add('dns', 'DNS lookup', $ip !== $parts['host'] ? 'ok' : 'fail', $ip !== $parts['host'] ? "{$parts['host']} -> $ip" : "cannot resolve {$parts['host']}", 'SS-UPL-2002');
            $health = preg_replace('#/calls/?$#', '/health', $endpoint, -1, $n);
            if ($n === 1 && $ip !== $parts['host']) {
                $headers = [];
                $ch = curl_init($health);
                curl_setopt_array($ch, [
                    CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15, CURLOPT_CONNECTTIMEOUT => 8,
                    CURLOPT_SSL_VERIFYPEER => (bool) $cfg['general']['verify_tls'], CURLOPT_SSL_VERIFYHOST => $cfg['general']['verify_tls'] ? 2 : 0,
                    CURLOPT_HTTPHEADER => ['User-Agent: SedaSanj-doctor/PHP ' . PHP_VERSION],
                    CURLOPT_HEADERFUNCTION => function ($h, $line) use (&$headers) {
                        $p = explode(':', $line, 2);
                        if (count($p) === 2) {
                            $headers[strtolower(trim($p[0]))] = trim($p[1]);
                        }
                        return strlen($line);
                    },
                ]);
                $body = curl_exec($ch);
                $errno = curl_errno($ch);
                $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
                $ms = (int) round(((float) curl_getinfo($ch, CURLINFO_TOTAL_TIME)) * 1000);
                $error = curl_error($ch);
                curl_close($ch);
                if ($body === false) {
                    $add('health', 'API health endpoint', 'fail', "$error (curl $errno)", ErrorCatalog::forCurlErrno($errno));
                } else {
                    $add('health', 'API health endpoint', $status >= 200 && $status < 300 ? 'ok' : 'fail', "HTTP $status in {$ms} ms", $status >= 200 && $status < 300 ? '' : ErrorCatalog::forHttpStatus($status));
                    if (isset($headers['date']) && ($remote = strtotime($headers['date'])) !== false) {
                        $skew = abs(time() - $remote);
                        $add('clock', 'Clock versus server', $skew > 120 ? 'warn' : 'ok', "difference {$skew}s", 'SS-SYS-1006');
                    }
                }
            }
        }
    }

    // Recent error codes in the log
    $codes = [];
    $logFile = (string) $cfg['logging']['log_file'];
    if (is_readable($logFile)) {
        $size = filesize($logFile);
        $fh = fopen($logFile, 'r');
        if ($fh) {
            if ($size > 1048576) {
                fseek($fh, $size - 1048576);
            }
            while (($line = fgets($fh)) !== false) {
                if (preg_match('/\b(ERROR|WARNING)\b.*code=(SS-[A-Z]{3,4}-\d{4})/', $line, $m)) {
                    $codes[$m[2]] = ($codes[$m[2]] ?? 0) + 1;
                }
            }
            fclose($fh);
        }
    }
    arsort($codes);

    $failed = 0;
    foreach ($checks as $c) {
        $failed += $c['status'] === 'fail' ? 1 : 0;
    }
    return [
        'generated_at' => gmdate('c'),
        'ok' => $failed === 0,
        'failed' => $failed,
        'checks' => $checks,
        'queue' => $summary,
        'recent_codes' => $codes,
        'host' => ['php' => PHP_VERSION, 'os' => php_uname('s') . ' ' . php_uname('r'), 'user' => get_current_user()],
    ];
}

function doctor_main(array $argv): int
{
    $configPath = null;
    $json = false;
    $network = true;
    foreach (array_slice($argv, 1) as $arg) {
        if ($arg === '--json') {
            $json = true;
        } elseif ($arg === '--no-network') {
            $network = false;
        } elseif (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, strlen('--config='));
        }
    }
    try {
        $cfg = Config::load($configPath);
    } catch (ConfigError $exc) {
        $message = Logger::redact($exc->getMessage());
        if ($json) {
            echo json_encode(['ok' => false, 'config_error' => $message, 'code' => 'SS-CFG-1001'], JSON_PRETTY_PRINT) . "\n";
        } else {
            fwrite(STDERR, "SS-CFG-1001 Config error: {$message}\n");
        }
        return 2;
    }
    $report = doctor_run($cfg, $network);
    if ($json) {
        echo json_encode($report, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
        return $report['ok'] ? 0 : 1;
    }
    foreach ($report['checks'] as $c) {
        $mark = ['ok' => 'OK  ', 'warn' => 'WARN', 'fail' => 'FAIL'][$c['status']];
        echo sprintf("[%s] %-34s %s%s\n", $mark, $c['label'], $c['detail'], $c['code'] !== '' && $c['status'] !== 'ok' ? "  [{$c['code']}]" : '');
        if ($c['status'] !== 'ok' && $c['action'] !== '') {
            echo "       -> {$c['action']}\n";
        }
    }
    if ($report['recent_codes']) {
        echo "\nError codes in the recent log:\n";
        foreach ($report['recent_codes'] as $code => $count) {
            echo "  $count x $code  " . ErrorCatalog::helpUrl($code) . "\n";
        }
    }
    echo "\n" . ($report['ok'] ? 'All required checks passed.' : "{$report['failed']} required check(s) failed.") . "\n";
    return $report['ok'] ? 0 : 1;
}

// Run only when executed directly; support-bundle.php includes this file for doctor_run().
if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(doctor_main($argv));
}
