<?php
/**
 * FailedRequeue.php - moves recordings from failed/ back into the retry queue.
 * Shared by requeue-failed.php (operator retry) and recover-unresolved.php
 * (call metadata recovered from the CDR). Nothing is deleted: audio and its
 * metadata travel together, and the manifest is removed only after the job is
 * safely queued.
 */

namespace Engine;

class FailedRequeue
{
    /**
     * @param callable(array,array):array $prepare Receives (metadata, manifest) and returns
     *        ['metadata' => array] to proceed, or ['skip' => reason, 'unresolved' => bool].
     * @param list<string>|null $codes Only manifests with one of these error codes.
     * @return array{recovered:int,skipped:int,problems:int,unresolved:int}
     */
    public static function run(
        array $cfg,
        Logger $log,
        callable $prepare,
        bool $dryRun = false,
        ?array $codes = null,
        int $olderThanSeconds = 0,
        int $limit = 0
    ): array {
        $failedDir = rtrim($cfg['queue']['failed_dir'], '/');
        $spoolDir = rtrim($cfg['queue']['spool_dir'], '/');
        $queue = Queue::create($cfg);
        $summary = ['recovered' => 0, 'skipped' => 0, 'problems' => 0, 'unresolved' => 0];
        $seen = 0;
        $now = time();

        foreach (glob($failedDir . '/*.json') ?: [] as $manifestPath) {
            if (!preg_match('/^[0-9a-f]{64}\.json$/', basename($manifestPath))) {
                continue; // metadata sidecars and job files are handled through their manifest
            }
            if ($limit > 0 && $seen >= $limit) {
                break;
            }
            $manifest = json_decode((string) @file_get_contents($manifestPath), true);
            if (!is_array($manifest) || empty($manifest['metadata'])) {
                $summary['skipped']++;
                continue;
            }
            if ($codes !== null && !in_array((string) ($manifest['error_code'] ?? ''), $codes, true)) {
                $summary['skipped']++;
                continue;
            }
            [$audio, $sidecar] = self::files($manifest, $failedDir);
            if ($audio === null) {
                $log->warning('Cannot re-queue: the recording is no longer in failed/', [
                    'manifest' => basename($manifestPath),
                ]);
                $summary['problems']++;
                continue;
            }
            if ($olderThanSeconds > 0 && $now - (int) @filemtime($audio) < $olderThanSeconds) {
                $summary['skipped']++;
                continue;
            }
            $seen++;

            $prepared = $prepare($manifest['metadata'], $manifest);
            if (!empty($prepared['skip'])) {
                $summary['skipped']++;
                if (!empty($prepared['unresolved'])) {
                    $summary['unresolved']++;
                }
                $log->coded('SS-SWP-1001', 'Failed recording was not recovered: ' . $prepared['skip'], [
                    'manifest' => basename($manifestPath),
                    'uniqueid' => (string) ($manifest['metadata']['uniqueid'] ?? ''),
                ]);
                continue;
            }
            $metadata = $prepared['metadata'] ?? $manifest['metadata'];

            $name = preg_replace('/\.\d{10}$/', '', basename($audio));
            $dest = $spoolDir . '/' . $name;
            if ($dryRun) {
                echo "would re-queue {$name}\n";
                $summary['recovered']++;
                continue;
            }
            if (!is_dir($spoolDir) && !@mkdir($spoolDir, 0755, true)) {
                $log->coded('SS-SYS-1007', "Cannot create {$spoolDir}");
                $summary['problems']++;
                continue;
            }
            if (file_exists($dest) || !@rename($audio, $dest)) {
                $log->warning('Cannot re-queue: destination exists or move failed', ['file' => $name]);
                $summary['problems']++;
                continue;
            }
            $restoredSidecar = null;
            if (!self::writeSidecar($dest, $metadata)) {
                @rename($dest, $audio);
                $log->coded('SS-STG-1007', 'Cannot rewrite the metadata sidecar for ' . $dest);
                $summary['problems']++;
                continue;
            }
            if ($sidecar !== null) {
                $restoredSidecar = $sidecar;
                @unlink($sidecar); // superseded by the rewritten sidecar next to the audio
            }
            try {
                $jobId = $queue->spool($dest, null, $metadata, 'requeued from failed/');
                $job = $queue->get($jobId);
                if ($job !== null) {
                    $job['attempts'] = 0;
                    $job['status'] = 'pending';
                    $job['next_attempt_epoch'] = microtime(true);
                    unset($job['metadata_deadline_epoch']);
                    $queue->save($job);
                }
            } catch (\Throwable $exc) {
                // put it back: never leave a recording without a record
                @rename($dest, $audio);
                if ($restoredSidecar !== null) {
                    @rename($dest . '.metadata.json', $restoredSidecar);
                } else {
                    @unlink($dest . '.metadata.json');
                }
                $log->coded('SS-QUE-1002', 'Cannot queue the recording again: ' . $exc->getMessage());
                $summary['problems']++;
                continue;
            }
            @unlink($manifestPath);
            $key = (string) ($metadata['_state_key'] ?? $dest);
            StateStore::record($cfg, $key, 'spooled', ['source' => 'requeue', 'job_id' => $jobId]);
            $log->info('Recording re-queued from failed/', [
                'uniqueid' => (string) ($metadata['uniqueid'] ?? ''),
                'job_id' => $jobId,
            ]);
            $summary['recovered']++;
        }

        return $summary;
    }

    /** @return array{0:?string,1:?string} audio, metadata sidecar */
    private static function files(array $manifest, string $failedDir): array
    {
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
        return [$audio, $sidecar];
    }

    private static function writeSidecar(string $dest, array $metadata): bool
    {
        $path = $dest . '.metadata.json';
        $temporary = $path . '.tmp.' . getmypid();
        $encoded = json_encode($metadata, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
        if ($encoded === false || file_put_contents($temporary, $encoded, LOCK_EX) === false) {
            @unlink($temporary);
            return false;
        }
        if (!@rename($temporary, $path)) {
            @unlink($temporary);
            return false;
        }
        return true;
    }
}
