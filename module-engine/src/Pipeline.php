<?php
/**
 * Pipeline.php - post-upload / delivery orchestration. Ported from the
 * remainder of common.py: handle_post_upload(), finalize_successful_upload(),
 * move_to_failed(), deliver_staged(). Ties Uploader + Queue + Staging
 * together the same way uploader.py / sweeper.py / queue_worker.py did.
 */

namespace Engine;

class Pipeline
{
    public static function handlePostUpload(array $cfg, string $filepath, Logger $log): void
    {
        $action = $cfg['post_upload']['on_success'];
        if ($action === 'delete') {
            if (@unlink($filepath)) {
                $log->info("Deleted local recording {$filepath} after successful upload");
            } else {
                $log->warning("Could not delete {$filepath}");
            }
        } elseif ($action === 'move') {
            $moveDir = $cfg['post_upload']['move_dir'];
            if ($moveDir) {
                if (!is_dir($moveDir)) {
                    @mkdir($moveDir, 0755, true);
                }
                $dest = rtrim($moveDir, '/') . '/' . basename($filepath);
                if (@rename($filepath, $dest)) {
                    $log->info("Moved {$filepath} -> {$dest}");
                } else {
                    $log->warning("Could not move {$filepath} -> {$dest}");
                }
            }
        }
    }

    public static function finalizeSuccessfulUpload(array $cfg, string $stagedPath, ?string $archivePath, Logger $log): void
    {
        if (@unlink($stagedPath)) {
            $log->debug("Removed staged file {$stagedPath} after successful upload");
        } else {
            $log->warning("Could not remove staged file {$stagedPath}");
        }
        @unlink($stagedPath . '.metadata.json');
        if ($archivePath !== null && $archivePath !== '') {
            self::handlePostUpload($cfg, $archivePath, $log);
        }
    }

    /** @return string[] paths moved */
    public static function moveToFailed(array $cfg, ?string $audioPath, ?string $jobPath, Logger $log, array $details = []): array
    {
        $failedDir = $cfg['queue']['failed_dir'];
        if (!is_dir($failedDir) && !@mkdir($failedDir, 0755, true)) {
            $log->coded('SS-SYS-1007', "Could not create failed folder {$failedDir}; leaving {$audioPath} in place");
            return [];
        }

        if ($audioPath && !is_file($audioPath)) {
            $log->warning("Audio {$audioPath} to be moved to the failed folder no longer exists");
        }
        $sources = array_filter([
            $audioPath,
            $audioPath ? $audioPath . '.metadata.json' : null,
            $jobPath,
            isset($details['metadata']['_sidecar_path']) ? $details['metadata']['_sidecar_path'] : null,
        ], fn($p) => $p && is_file($p));
        $sources = array_values(array_unique($sources));

        $suffix = '';
        foreach ($sources as $src) {
            if (is_file(rtrim($failedDir, '/') . '/' . basename($src))) {
                $suffix = '.' . time();
                break;
            }
        }

        $moved = [];
        foreach ($sources as $src) {
            $dest = rtrim($failedDir, '/') . '/' . basename($src) . $suffix;
            if (@rename($src, $dest)) {
                $moved[] = $dest;
            } else {
                $log->error("Could not move {$src} to the failed folder");
            }
        }
        if ($moved || $details) {
            $manifest = rtrim($failedDir, '/') . '/' . hash('sha256', implode('|', $moved)) . '.json';
            if (!$moved) {
                $manifest = rtrim($failedDir, '/') . '/' . hash('sha256', json_encode($details) . microtime(true)) . '.json';
            }
            $payload = array_merge($details, ['files' => $moved, 'failed_at' => gmdate('c')]);
            $temporary = $manifest . '.tmp.' . getmypid();
            $encoded = json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
            if ($encoded === false || @file_put_contents($temporary, $encoded, LOCK_EX) === false
                || !@rename($temporary, $manifest)) {
                @unlink($temporary);
                $log->error("Could not atomically write failed manifest {$manifest}");
            }
        }
        if ($moved) {
            $log->coded($details['error_code'] ?? 'SS-QUE-1004', 'Delivery failed for good; moved to the failed folder: ' . implode(', ', $moved), ['cause' => $details['error_code'] ?? '']);
        }
        return $moved;
    }

    /**
     * Upload a staged file, spooling it for retry on a retryable failure,
     * or moving it straight to the failed folder otherwise.
     *
     * @return array{0:string,1:?string,2:?string} [$outcome, $jobId, $error]
     *         $outcome is one of "uploaded" | "spooled" | "failed".
     */
    public static function deliverStaged(
        array $cfg,
        string $stagedPath,
        ?string $archivePath,
        array $metadata,
        bool $allowSpool,
        Logger $log
    ): array {
        try {
            Uploader::uploadWithImmediateRetries($cfg, $stagedPath, $metadata, $log->asClosure('WARNING'));
        } catch (UploadError $exc) {
            $ctx = ['uniqueid' => (string) ($metadata['uniqueid'] ?? $metadata['asterisk_uniqueid'] ?? '')] + $exc->context;
            $log->coded($exc->errorCode, "Upload failed: {$exc->getMessage()}", $ctx);
            if (!$allowSpool || !$exc->retryable) {
                self::moveToFailed($cfg, $stagedPath, $archivePath, $log, [
                    'metadata' => $metadata, 'error' => $exc->getMessage(), 'error_code' => $exc->errorCode, 'attempts' => 0,
                ]);
                return ['failed', null, $exc->getMessage()];
            }
            try {
                $queue = Queue::create($cfg);
                $jobId = $queue->spool($stagedPath, $archivePath, $metadata, $exc->getMessage());
                if ($exc->creditBlocked || $exc->configBlocked) {
                    $job = $queue->get($jobId);
                    if ($job !== null) {
                        $job['status'] = $exc->creditBlocked ? 'blocked_credit' : 'blocked_config';
                        $delay = $exc->creditBlocked
                            ? (int) ($cfg['queue']['credit_retry_seconds'] ?? 3600)
                            : (int) ($cfg['queue']['config_retry_seconds'] ?? 3600);
                        $job['next_attempt_epoch'] = microtime(true) + $delay;
                        $queue->save($job);
                    }
                }
            } catch (\Throwable $spoolExc) {
                $log->coded('SS-QUE-1002', "Could not spool job either: {$spoolExc->getMessage()}", $ctx);
                self::moveToFailed($cfg, $stagedPath, $archivePath, $log, [
                    'metadata' => $metadata,
                    'error' => $spoolExc->getMessage(),
                    'error_code' => 'SS-QUE-1002',
                    'attempts' => 0,
                ]);
                return ['failed', null, "upload failed and could not spool: {$spoolExc->getMessage()}"];
            }
            return ['spooled', $jobId, $exc->getMessage()];
        }

        self::finalizeSuccessfulUpload($cfg, $stagedPath, $archivePath, $log);
        return ['uploaded', null, null];
    }
}
