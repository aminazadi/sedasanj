<?php
/**
 * QueueWorker.php - processes due retry jobs. Ported from queue_worker.py.
 */

namespace Engine;

class QueueWorker
{
    public static function processJob(array $cfg, array $job, QueueInterface $queue, Logger $log): void
    {
        $jobId = $job['job_id'];
        $filepath = $job['filepath'];
        $metadata = $job['metadata'];

        if (!is_file($filepath)) {
            $log->error("Recording for job {$jobId} no longer exists at {$filepath}; dropping job");
            Pipeline::moveToFailed($cfg, null, null, $log, [
                'metadata' => $metadata,
                'error' => 'local file disappeared before delivery',
                'attempts' => $job['attempts'] ?? 0,
                'created_epoch' => $job['created_epoch'] ?? null,
            ]);
            StateStore::record($cfg, (string) ($metadata['_state_key'] ?? $filepath), 'failed', [
                'source' => 'queue_worker', 'job_id' => $jobId,
                'last_error' => 'local file disappeared before delivery',
            ]);
            $queue->remove($jobId);
            return;
        }

        try {
            Uploader::uploadFile($cfg, $filepath, $metadata, $log->asClosure('DEBUG'));
        } catch (UploadError $exc) {
            if ($exc->creditBlocked) {
                $delay = (int) ($cfg['queue']['credit_retry_seconds'] ?? 3600);
                $job['status'] = 'blocked_credit';
                $job['last_error'] = $exc->getMessage();
                $job['next_attempt_epoch'] = microtime(true) + $delay;
                $queue->save($job);
                $log->warning("Job {$jobId} is blocked by credit; retrying in {$delay}s without consuming an attempt");
                StateStore::record($cfg, (string) ($metadata['_state_key'] ?? $filepath), 'blocked_credit', [
                    'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
                ]);
                return;
            }
            $job['attempts'] = ($job['attempts'] ?? 0) + 1;
            $job['status'] = 'pending';
            $job['last_error'] = $exc->getMessage();

            if (!$exc->retryable || $job['attempts'] >= $cfg['queue']['max_retries']) {
                $queue->save($job);
                Pipeline::moveToFailed($cfg, $filepath, $job['archive_path'] ?? null, $log, [
                    'metadata' => $metadata,
                    'error' => $exc->getMessage(),
                    'attempts' => $job['attempts'],
                    'created_epoch' => $job['created_epoch'] ?? null,
                ]);
                $queue->remove($jobId);
                StateStore::record($cfg, (string) ($metadata['_state_key'] ?? $filepath), 'failed', [
                    'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
                ]);
                return;
            }

            $delay = Queue::backoffSeconds($cfg, $job['attempts']);
            $job['next_attempt_epoch'] = microtime(true) + $delay;
            $queue->save($job);
            $log->warning("Job {$jobId} attempt {$job['attempts']} failed ({$exc->getMessage()}); retrying in {$delay}s");
            StateStore::record($cfg, (string) ($metadata['_state_key'] ?? $filepath), 'spooled', [
                'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
            ]);
            return;
        }

        $attempts = ($job['attempts'] ?? 0) + 1;
        $log->info("Job {$jobId} succeeded on retry attempt {$attempts}");
        $archivePath = $job['archive_path'] ?? null;
        if ($archivePath) {
            Pipeline::finalizeSuccessfulUpload($cfg, $filepath, $archivePath, $log);
        } else {
            // Job was spooled by a pre-upgrade version and has no
            // archive_path - fall back to applying on_success directly.
            if (empty($metadata['_voicemail'])) {
                Pipeline::handlePostUpload($cfg, $filepath, $log);
            } else {
                @unlink($filepath);
                @unlink($filepath . '.metadata.json');
            }
        }
        StateStore::record($cfg, (string) ($metadata['_state_key'] ?? $filepath), 'uploaded', ['source' => 'queue_worker', 'job_id' => $jobId]);
        if (!empty($metadata['_sidecar_path'])) {
            @unlink($metadata['_sidecar_path']);
        }
        @unlink($filepath . '.metadata.json');
        $queue->remove($jobId);
    }

    public static function tick(array $cfg, Logger $log): void
    {
        $queue = Queue::create($cfg);
        foreach ($queue->dueJobs() as $job) {
            try {
                self::processJob($cfg, $job, $queue, $log);
            } catch (\Throwable $exc) {
                $log->error("Unexpected error processing job {$job['job_id']}: {$exc->getMessage()}");
            }
        }
    }
}
