#!/usr/bin/env php
<?php
/**
 * bin/requeue-failed.php - puts recordings that were moved to failed/ back into the retry queue,
 * for example after a wrong API key or endpoint was corrected. Nothing is deleted: a recording is
 * moved back together with its metadata, and its failure manifest is removed only after the job is
 * safely queued. See bin/recover-unresolved.php for call numbers recovered from the CDR.
 *
 *   php requeue-failed.php [--config=...] [--code=SS-UPL-0401] [--dry-run] [--limit=N]
 *
 * Without --code every failed recording is re-queued. Exit code 0 = done, 1 = some entries could not
 * be re-queued (they stay in failed/), 2 = configuration error.
 */

require_once __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\FailedRequeue;
use Engine\Logger;

function requeue_main(array $argv): int
{
    $configPath = null;
    $code = null;
    $dry = false;
    $limit = 0;
    foreach (array_slice($argv, 1) as $arg) {
        if (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, 9);
        } elseif (str_starts_with($arg, '--code=')) {
            $code = substr($arg, 7);
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
    $log = new Logger($cfg, 'aru.requeue');
    $summary = FailedRequeue::run(
        $cfg,
        $log,
        static function (array $metadata, array $manifest): array {
            return ['metadata' => $metadata];
        },
        $dry,
        $code === null ? null : [$code],
        0,
        $limit
    );
    echo "re-queued: {$summary['recovered']}, skipped: {$summary['skipped']}, problems: {$summary['problems']}\n";
    return $summary['problems'] > 0 ? 1 : 0;
}

if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(requeue_main($argv));
}
