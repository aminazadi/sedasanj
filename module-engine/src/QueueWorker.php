<?php
/**
 * QueueWorker.php - processes due retry jobs. Ported from queue_worker.py.
 */

namespace Engine;

class QueueWorker
{
    /** Outcomes: 'done', 'dropped', 'retry', 'down' (endpoint unreachable/5xx), 'blocked' (credit/config), 'failed'. */
    public static function processJob(array $cfg, array $job, QueueInterface $queue, Logger $log): string
    {
        $jobId = $job['job_id'];
        $filepath = $job['filepath'];
        $metadata = $job['metadata'];
        $uniqueid = (string) ($metadata['uniqueid'] ?? $metadata['asterisk_uniqueid'] ?? '');
        $stateKey = (string) ($metadata['_state_key'] ?? $filepath);

        if (!is_file($filepath)) {
            // The recording can legitimately vanish because the hook-side upload of the same
            // call just succeeded and cleaned up; do not turn that into a false failure.
            if (StateStore::statusOf($cfg, $stateKey) === 'uploaded') {
                $log->info("Job {$jobId} already delivered by another process; dropping job", ['uniqueid' => $uniqueid]);
                $queue->remove($jobId);
                return 'dropped';
            }
            $log->coded('SS-QUE-1001', "Recording for job {$jobId} no longer exists at {$filepath}; dropping job", ['uniqueid' => $uniqueid]);
            Pipeline::moveToFailed($cfg, null, null, $log, [
                'metadata' => $metadata,
                'error' => 'local file disappeared before delivery',
                'error_code' => 'SS-QUE-1001',
                'attempts' => $job['attempts'] ?? 0,
                'created_epoch' => $job['created_epoch'] ?? null,
            ]);
            StateStore::record($cfg, $stateKey, 'failed', [
                'source' => 'queue_worker', 'job_id' => $jobId,
                'last_error' => 'local file disappeared before delivery',
            ]);
            $queue->remove($jobId);
            return 'dropped';
        }

        try {
            $result = Uploader::uploadFile($cfg, $filepath, $metadata, $log->asClosure('DEBUG'));
            if (!empty($result['replayed'])) {
                $log->coded('SS-UPL-1003', "Server reports job {$jobId} was already received", [
                    'uniqueid' => $uniqueid, 'server_request_id' => $result['info']['server_request_id'] ?? '',
                ]);
            }
        } catch (UploadError $exc) {
            $ctx = ['uniqueid' => $uniqueid, 'job_id' => $jobId, 'attempt' => ($job['attempts'] ?? 0) + 1] + $exc->context;
            if ($exc->creditBlocked || $exc->configBlocked) {
                $delay = $exc->creditBlocked
                    ? (int) ($cfg['queue']['credit_retry_seconds'] ?? 3600)
                    : (int) ($cfg['queue']['config_retry_seconds'] ?? 3600);
                $job['status'] = $exc->creditBlocked ? 'blocked_credit' : 'blocked_config';
                $job['last_error'] = $exc->getMessage() . ' [' . $exc->errorCode . ']';
                $job['last_error_code'] = $exc->errorCode;
                $job['next_attempt_epoch'] = microtime(true) + $delay;
                $queue->save($job);
                $log->coded($exc->creditBlocked ? 'SS-QUE-1005' : 'SS-QUE-1006', "Job {$jobId} is paused ({$exc->getMessage()}); retrying in {$delay}s without consuming an attempt", ['cause' => $exc->errorCode] + $ctx);
                StateStore::record($cfg, $stateKey, $job['status'], [
                    'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
                ]);
                return 'blocked';
            }
            $job['attempts'] = ($job['attempts'] ?? 0) + 1;
            $job['status'] = 'pending';
            $job['last_error'] = $exc->getMessage() . ' [' . $exc->errorCode . ']';
            $job['last_error_code'] = $exc->errorCode;

            if (!$exc->retryable || $job['attempts'] >= $cfg['queue']['max_retries']) {
                $queue->save($job);
                $log->coded('SS-QUE-1004', "Job {$jobId} failed permanently: {$exc->getMessage()}", ['cause' => $exc->errorCode] + $ctx);
                Pipeline::moveToFailed($cfg, $filepath, $job['archive_path'] ?? null, $log, [
                    'metadata' => $metadata,
                    'error' => $exc->getMessage(),
                    'error_code' => $exc->errorCode,
                    'attempts' => $job['attempts'],
                    'created_epoch' => $job['created_epoch'] ?? null,
                ]);
                $queue->remove($jobId);
                StateStore::record($cfg, $stateKey, 'failed', [
                    'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
                ]);
                return 'failed';
            }

            // Honour the server's Retry-After (rate limits) when it asks for more than our backoff.
            $delay = max(Queue::backoffSeconds($cfg, $job['attempts']), (int) ($exc->context['retry_after'] ?? 0));
            $job['next_attempt_epoch'] = microtime(true) + $delay;
            $queue->save($job);
            $log->coded('SS-QUE-1003', "Job {$jobId} attempt {$job['attempts']} failed ({$exc->getMessage()}); retrying in {$delay}s", ['cause' => $exc->errorCode, 'retry_in_s' => $delay] + $ctx);
            StateStore::record($cfg, $stateKey, 'spooled', [
                'source' => 'queue_worker', 'job_id' => $jobId, 'last_error' => $exc->getMessage(),
            ]);
            return in_array($exc->errorCode, ['SS-UPL-2001', 'SS-UPL-2002', 'SS-UPL-2003', 'SS-UPL-2004', 'SS-UPL-2005', 'SS-UPL-0500'], true) ? 'down' : 'retry';
        }

        $attempts = ($job['attempts'] ?? 0) + 1;
        $log->info("Job {$jobId} succeeded on retry attempt {$attempts}");
        $archivePath = $job['archive_path'] ?? null;
        if ($archivePath || empty($metadata['_voicemail'])) {
            // A null archive path means the local archive copy was skipped; just clean up the staged file.
            Pipeline::finalizeSuccessfulUpload($cfg, $filepath, $archivePath ?: null, $log);
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
        return 'done';
    }

    /**
     * Processes due jobs. Stops early when the endpoint itself is unhealthy (network failure,
     * 5xx, credit/config pause) - the remaining jobs would fail the same way and each wait out
     * a full timeout - and never runs longer than $budgetSeconds so the sweeper, voicemail and
     * missed-call loops sharing this process are not starved.
     */
    public static function tick(array $cfg, Logger $log, int $budgetSeconds = 120): void
    {
        $queue = Queue::create($cfg);
        $deadline = microtime(true) + $budgetSeconds;
        foreach ($queue->dueJobs() as $job) {
            if (microtime(true) >= $deadline) {
                $log->info('Queue tick time budget reached; remaining jobs wait for the next tick', ['budget_s' => $budgetSeconds]);
                break;
            }
            try {
                $outcome = self::processJob($cfg, $job, $queue, $log);
            } catch (\Throwable $exc) {
                $log->coded('SS-SVC-1003', "Unexpected error processing job {$job['job_id']}: {$exc->getMessage()}");
                continue;
            }
            if ($outcome === 'blocked' || $outcome === 'down') {
                break;
            }
        }
    }
}
