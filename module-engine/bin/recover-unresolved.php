#!/usr/bin/env php
<?php
/**
 * bin/recover-unresolved.php - re-queues recordings that failed because their caller or
 * dialed number was a dialplan label (for example FreePBX's "recordcheck") or because the
 * CDR had not finalized yet. Unlike requeue-failed.php, it only moves a recording when the
 * numbers are now resolved with confidence from the CDR (or an unambiguous dialplan value).
 * Everything else stays in failed/ with a coded log line; nothing is deleted.
 *
 *   php recover-unresolved.php [--config=...] [--code=SS-UPL-0422] [--older-than=60]
 *                              [--limit=N] [--dry-run]
 *
 * Exit code 0 = every candidate was recovered, 1 = some stayed unresolved, 2 = configuration error.
 */

require_once __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\FailedRequeue;
use Engine\IngestMapper;
use Engine\Logger;

function recover_unresolved_main(array $argv): int
{
    $configPath = null;
    $selectedCode = null;
    $dry = false;
    $limit = 0;
    $olderThan = 60;
    foreach (array_slice($argv, 1) as $arg) {
        if (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, 9);
        } elseif (str_starts_with($arg, '--code=')) {
            $selectedCode = substr($arg, 7);
        } elseif (str_starts_with($arg, '--older-than=')) {
            $olderThan = max(0, (int) substr($arg, 13));
        } elseif (str_starts_with($arg, '--limit=')) {
            $limit = max(0, (int) substr($arg, 8));
        } elseif ($arg === '--dry-run') {
            $dry = true;
        }
    }
    try {
        $cfg = Config::load($configPath);
    } catch (ConfigError $exc) {
        fwrite(STDERR, 'SS-CFG-1001 Config error: ' . Logger::redact($exc->getMessage()) . "\n");
        return 2;
    }
    $log = new Logger($cfg, 'aru.recover');

    if ($selectedCode === null) {
        $codes = ['SS-UPL-0422', 'SS-UPL-1004'];
    } else {
        $codes = $selectedCode === 'all' ? null : [$selectedCode];
    }
    $summary = FailedRequeue::run(
        $cfg,
        $log,
        static function (array $metadata, array $manifest): array {
            $resolved = IngestMapper::toIngestForm($metadata);
            if (($resolved['pbx_evidence'] ?? '') === 'ambiguous') {
                return ['skip' => 'CDR evidence is ambiguous', 'unresolved' => true];
            }
            if (empty($resolved['caller_number']) || empty($resolved['dialed_number'])) {
                return ['skip' => 'caller or dialed number is still unresolved', 'unresolved' => true];
            }
            $merged = $metadata;
            if (empty($resolved['direction'])) {
                unset($merged['direction']);
            }
            foreach ([
                'direction', 'asterisk_uniqueid', 'started_at', 'ended_at',
                'agent_extension', 'caller_extension', 'dialed_extension', 'pbx_evidence',
            ] as $key) {
                if (!empty($resolved[$key])) {
                    $merged[$key] = $resolved[$key];
                }
            }
            $merged['caller_number'] = $resolved['caller_number'];
            $merged['dialed_number'] = $resolved['dialed_number'];
            $merged['_recovered_at'] = gmdate('Y-m-d\TH:i:s\Z');
            $merged['_recovered_from'] = 'cdr';
            return ['metadata' => $merged];
        },
        $dry,
        $codes,
        $olderThan,
        $limit
    );

    echo "recovered: {$summary['recovered']}, unresolved: {$summary['unresolved']}, "
        . "skipped: {$summary['skipped']}, problems: {$summary['problems']}\n";
    return ($summary['problems'] > 0 || $summary['unresolved'] > 0) ? 1 : 0;
}

if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(recover_unresolved_main($argv));
}
