#!/usr/bin/env php
<?php
/**
 * bin/support-bundle.php - collects what support needs to diagnose a PBX into one .tar.gz:
 * doctor report, redacted config, recent logs, queue/failed summaries, versions and service state.
 * Everything is passed through Logger::redact() and config secrets are blanked, so the archive is
 * safe to attach to a ticket. Caller IDs are masked unless --include-numbers is given.
 *
 *   php support-bundle.php --out=/path/bundle.tar.gz [--config=...] [--include-numbers]
 */

require_once __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\Logger;

function bundle_redact_config(string $ini): string
{
    $out = [];
    foreach (preg_split('/\R/', $ini) as $line) {
        if (preg_match('/^\s*(api_key|api_key_b64|archive_password|archive_password_b64|extra_headers|secret|token|password)\s*=/i', $line, $m)) {
            $out[] = $m[1] . ' = [REDACTED]';
        } else {
            $out[] = Logger::redact($line);
        }
    }
    return implode("\n", $out) . "\n";
}

function bundle_tail(string $path, int $bytes): string
{
    if (!is_readable($path)) {
        return '';
    }
    $size = filesize($path);
    $fh = fopen($path, 'r');
    if (!$fh) {
        return '';
    }
    if ($size > $bytes) {
        fseek($fh, $size - $bytes);
        fgets($fh);
    }
    $text = stream_get_contents($fh);
    fclose($fh);
    return (string) $text;
}

function bundle_mask_numbers(string $text): string
{
    // Mask runs of 7+ digits (phone numbers) to their last three digits.
    return preg_replace_callback('/\d{7,}/', function ($m) {
        return str_repeat('*', strlen($m[0]) - 3) . substr($m[0], -3);
    }, $text) ?? $text;
}

function bundle_main(array $argv): int
{
    $configPath = null;
    $out = '';
    $numbers = false;
    foreach (array_slice($argv, 1) as $arg) {
        if (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, 9);
        } elseif (str_starts_with($arg, '--out=')) {
            $out = substr($arg, 6);
        } elseif ($arg === '--include-numbers') {
            $numbers = true;
        }
    }
    if ($out === '') {
        fwrite(STDERR, "usage: support-bundle.php --out=/path/bundle.tar.gz [--config=...] [--include-numbers]\n");
        return 1;
    }
    $iniPath = $configPath ?? (getenv('ARU_CONFIG') ?: '/etc/asterisk-recording-uploader/config.ini');
    $workDir = sys_get_temp_dir() . '/sedasanj-bundle-' . bin2hex(random_bytes(6));
    if (!@mkdir($workDir, 0700, true)) {
        fwrite(STDERR, "cannot create $workDir\n");
        return 1;
    }
    $root = $workDir . '/sedasanj-support';
    mkdir($root, 0700);
    $mask = $numbers ? function (string $t): string { return $t; } : 'bundle_mask_numbers';
    $write = function (string $name, string $content) use ($root, $mask): void {
        file_put_contents("$root/$name", $mask(Logger::redact($content)));
    };

    $write('README.txt', "Seda Sanj support bundle generated " . gmdate('c') . "\nSecrets are removed. Numbers masked: " . ($numbers ? 'no' : 'yes') . "\n");
    $write('config.ini', is_readable($iniPath) ? bundle_redact_config((string) file_get_contents($iniPath)) : "config not readable: $iniPath\n");

    try {
        $cfg = Config::load($configPath);
    } catch (ConfigError $exc) {
        $cfg = null;
        $write('config-error.txt', $exc->getMessage() . "\n");
    }

    $moduleXml = dirname(__DIR__, 2) . '/module.xml';
    $write('module.xml', is_readable($moduleXml) ? (string) file_get_contents($moduleXml) : '');

    $doctor = $cfg ? json_encode(doctor_bundle_report($cfg), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) : '{}';
    $write('doctor.json', (string) $doctor);

    if ($cfg) {
        $logFile = (string) $cfg['logging']['log_file'];
        $write('log-current.txt', bundle_tail($logFile, 2 * 1024 * 1024));
        $write('log-previous.txt', bundle_tail($logFile . '.1', 1024 * 1024));
        $failed = [];
        foreach (glob(rtrim($cfg['queue']['failed_dir'], '/') . '/*.json') ?: [] as $manifest) {
            if (preg_match('/^[0-9a-f]{64}\.json$/', basename($manifest))) {
                $data = json_decode((string) @file_get_contents($manifest), true);
                if (is_array($data)) {
                    unset($data['metadata']);
                    $failed[] = $data;
                }
            }
        }
        $write('failed-manifests.json', json_encode(array_slice($failed, -50), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
    }

    $commands = [
        'system.txt' => 'uname -a; echo; df -h 2>&1 | head -30; echo; free -m 2>&1; echo; date -u; echo; id',
        'versions.txt' => 'fwconsole --version 2>&1; asterisk -V 2>&1; php -v 2>&1 | head -2; php -m 2>&1 | tr "\n" " "',
        'service.txt' => 'systemctl status asterisk-recording-uploader.service --no-pager 2>&1 | head -40',
        'journal.txt' => 'journalctl -u asterisk-recording-uploader.service -n 300 --no-pager 2>&1',
        'freepbx-modules.txt' => 'fwconsole ma list 2>&1 | head -80',
    ];
    foreach ($commands as $file => $command) {
        $write($file, (string) @shell_exec($command));
    }

    $tar = 'tar -C ' . escapeshellarg($workDir) . ' -czf ' . escapeshellarg($out) . ' sedasanj-support 2>&1';
    exec($tar, $tarOut, $status);
    exec('rm -rf ' . escapeshellarg($workDir));
    if ($status !== 0) {
        fwrite(STDERR, "tar failed: " . implode(' ', $tarOut) . "\n");
        return 1;
    }
    @chmod($out, 0600);
    echo $out . "\n";
    return 0;
}

/** Reuses doctor.php's checks. */
function doctor_bundle_report(array $cfg): array
{
    require_once __DIR__ . '/doctor.php';
    return doctor_run($cfg, true);
}

if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(bundle_main($argv));
}
