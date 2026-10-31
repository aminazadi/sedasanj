#!/usr/bin/env php
<?php
/**
 * bin/requeue-failed.php - puts recordings that were moved to failed/ back into the retry queue,
 * for example after a wrong API key or endpoint was corrected. Nothing is deleted: a recording is
 * moved back together with its metadata, and its failure manifest is removed only after the job is
 * safely queued.
 *
 *   php requeue-failed.php [--config=...] [--code=SS-UPL-0401] [--dry-run]
 *
 * Without --code every failed recording is re-queued. Exit code 0 = done, 1 = some entries could not
 * be re-queued (they stay in failed/), 2 = configuration error.
 */

require_once __DIR__ . '/../autoload.php';

use Engine\Config;
use Engine\ConfigError;
use Engine\Logger;
use Engine\Queue;
use Engine\StateStore;

function requeue_main(array $argv): int
{
    $configPath = null;
    $code = null;
    $dry = false;
    foreach (array_slice($argv, 1) as $arg) {
        if (str_starts_with($arg, '--config=')) {
            $configPath = substr($arg, 9);
        } elseif (str_starts_with($arg, '--code=')) {
            $code = substr($arg, 7);
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
    $failedDir = rtrim($cfg['queue']['failed_dir'], '/');
    $spoolDir = rtrim($cfg['queue']['spool_dir'], '/');
    $queue = Queue::create($cfg);
    $moved = 0;
    $skipped = 0;
    $problems = 0;

    foreach (glob($failedDir . '/*.json') ?: [] as $manifestPath) {
        if (!preg_match('/^[0-9a-f]{64}\.json$/', basename($manifestPath))) {
            continue; // metadata sidecars and job files are handled through their manifest
        }
        $manifest = json_decode((string) @file_get_contents($manifestPath), true);
        if (!is_array($manifest) || empty($manifest['metadata'])) {
            $skipped++;
            continue;
        }
        if ($code !== null && ($manifest['error_code'] ?? '') !== $code) {
            $skipped++;
            continue;
        }
        $audio = null;
        $sidecar = null;
        foreach ((array) ($manifest['files'] ?? []) as $file) {
            if (!is_string($file) || !is_file($file) || strpos(realpath($file) ?: '', $failedDir) !== 0) {
                continue;
            }
            if (preg_match('/\.metadata\.json(\.\d+)?$/', $file)) {
                $sidecar = $file;
            } elseif (!preg_match('/\.json(\.\d+)?$/', $file)) {
                $audio = $file;
            }
        }
        if ($audio === null) {
            $log->warning('Cannot re-queue: the recording is no longer in failed/', ['manifest' => basename($manifestPath)]);
            $problems++;
            continue;
        }
        $name = preg_replace('/\.\d{10}$/', '', basename($audio));
        $dest = $spoolDir . '/' . $name;
        if ($dry) {
            echo "would re-queue {$name}\n";
            $moved++;
            continue;
        }
        if (!is_dir($spoolDir) && !@mkdir($spoolDir, 0755, true)) {
            $log->coded('SS-SYS-1007', "Cannot create {$spoolDir}");
            return 1;
        }
        if (file_exists($dest) || !@rename($audio, $dest)) {
            $log->warning('Cannot re-queue: destination exists or move failed', ['file' => $name]);
            $problems++;
            continue;
        }
        if ($sidecar !== null) {
            @rename($sidecar, $dest . '.metadata.json');
        }
        try {
            $jobId = $queue->spool($dest, null, $manifest['metadata'], 'requeued from failed/');
            $job = $queue->get($jobId);
            if ($job !== null) {
                $job['attempts'] = 0;
                $job['status'] = 'pending';
                $job['next_attempt_epoch'] = microtime(true);
                $queue->save($job);
            }
        } catch (\Throwable $exc) {
            @rename($dest, $audio); // put it back: never leave a recording without a record
            $log->coded('SS-QUE-1002', 'Cannot queue the recording again: ' . $exc->getMessage());
            $problems++;
            continue;
        }
        @unlink($manifestPath);
        $key = (string) ($manifest['metadata']['_state_key'] ?? $dest);
        StateStore::record($cfg, $key, 'spooled', ['source' => 'requeue', 'job_id' => $jobId]);
        $log->info('Recording re-queued from failed/', ['uniqueid' => (string) ($manifest['metadata']['uniqueid'] ?? ''), 'job_id' => $jobId]);
        $moved++;
    }
    echo "re-queued: {$moved}, skipped: {$skipped}, problems: {$problems}\n";
    return $problems > 0 ? 1 : 0;
}

if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    exit(requeue_main($argv));
}
