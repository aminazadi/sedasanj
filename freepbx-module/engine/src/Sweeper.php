<?php
/**
 * Sweeper.php - reconciles Asterisk's recording tree against the state
 * store. Ported from sweeper.py. Only ever looks for merged stereo
 * recordings (stereo_<n>.wav) still sitting in the recording tree - once
 * a call has been staged, its stereo_ file is deleted and the recording
 * lives on only as the staged copy in the pending folder plus the mono
 * archive file. The sweeper never touches archive files.
 */

namespace Engine;

class Sweeper
{
    const STEREO_PREFIX = 'stereo_';

    private static function compileExcludes(array $cfg): array
    {
        $patterns = [];
        foreach (preg_split('/\R/', $cfg['state']['exclude_patterns'] ?? '') as $line) {
            $line = trim($line);
            if ($line !== '') {
                $patterns[] = self::toPcre($line);
            }
        }
        return $patterns;
    }

    /** Python re patterns are bare; wrap as a PCRE delimiter for preg_match. */
    private static function toPcre(string $pattern): string
    {
        return '#' . str_replace('#', '\#', $pattern) . '#';
    }

    private static function iterCandidateFiles(array $cfg): \Generator
    {
        $watchDir = $cfg['watcher']['watch_dir'];
        if (!is_dir($watchDir)) {
            return;
        }
        if (!empty($cfg['state']['recursive_scan'])) {
            $it = new \RecursiveIteratorIterator(
                new \RecursiveDirectoryIterator($watchDir, \FilesystemIterator::SKIP_DOTS)
            );
            foreach ($it as $file) {
                if ($file->isFile()) {
                    yield $file->getPathname();
                }
            }
        } else {
            foreach (scandir($watchDir) ?: [] as $name) {
                $full = "{$watchDir}/{$name}";
                if (is_file($full)) {
                    yield $full;
                }
            }
        }
    }

    private static function extractMetadata(string $filepath, string $pattern): array
    {
        $sidecar = $filepath . '.metadata.json';
        if (is_file($sidecar)) {
            $decoded = json_decode((string) @file_get_contents($sidecar), true);
            if (is_array($decoded)) {
                return $decoded;
            }
        }
        $filename = basename($filepath);
        $pcre = self::toPcre($pattern);
        if (preg_match($pcre, $filename, $m)) {
            $meta = array_filter($m, fn($k) => is_string($k), ARRAY_FILTER_USE_KEY);
            $meta['source_filename'] = $filename;
            return $meta;
        }
        return ['source_filename' => $filename];
    }

    private static function jobFileExists(array $cfg, ?string $jobId, QueueInterface $queue): bool
    {
        if (!$jobId) {
            return false;
        }
        return $queue->get($jobId) !== null;
    }

    private static function needsAction(array $cfg, ?array $entry, QueueInterface $queue): bool
    {
        if ($entry === null) {
            return true;
        }
        $status = $entry['status'] ?? null;
        if ($status === 'ignored' || $status === 'uploaded') {
            return false;
        }
        if ($status === 'spooled') {
            return !self::jobFileExists($cfg, $entry['job_id'] ?? null, $queue);
        }
        if (in_array($status, ['uploading', 'discovered'], true)) {
            $age = microtime(true) - ($entry['last_updated_epoch'] ?? 0);
            return $age > $cfg['state']['stale_processing_seconds'];
        }
        // "failed" (and "dead_letter", the pre-merge legacy name): a
        // stereo_ file still in the recording tree means staging/
        // archiving failed, so it's retried.
        return true;
    }

    private static function attemptRecovery(array $cfg, string $filepath, ?array $entry, Logger $log): string
    {
        $metaPattern = $cfg['watcher']['filename_pattern'];
        $metadata = $entry['metadata'] ?? self::extractMetadata($filepath, $metaPattern);
        $metadata['_sidecar_path'] = $filepath . '.metadata.json';

        $mappedMetadata = IngestMapper::toIngestForm($metadata);
        foreach (Config::REQUIRED_INGEST_FIELDS as $requiredField) {
            if (empty($mappedMetadata[$requiredField])) {
                $log->warning("Sweeper: retained orphan {$filepath}; metadata is incomplete");
                StateStore::record($cfg, $filepath, 'orphaned', [
                    'metadata' => $metadata,
                    'source' => 'sweeper',
                    'last_error' => 'metadata sidecar is missing or incomplete',
                ]);
                return 'failed';
            }
        }

        StateStore::record($cfg, $filepath, 'uploading', ['metadata' => $metadata, 'source' => 'sweeper']);

        try {
            [$stagedPath, $archivePath] = Staging::prepareRecording($cfg, $filepath, $log->asClosure('DEBUG'));
        } catch (\Throwable $exc) {
            $log->error("Sweeper: could not stage/archive {$filepath}: {$exc->getMessage()}");
            StateStore::record($cfg, $filepath, 'failed', [
                'source' => 'sweeper',
                'last_error' => "prepare_recording failed: {$exc->getMessage()}",
            ]);
            return 'failed';
        }

        [$outcome, $jobId, $error] = Pipeline::deliverStaged($cfg, $stagedPath, $archivePath, $metadata, true, $log);

        if ($outcome === 'uploaded') {
            $log->info("Sweeper: recovered {$filepath} by uploading it directly");
            StateStore::record($cfg, $filepath, 'uploaded', ['source' => 'sweeper']);
        } elseif ($outcome === 'spooled') {
            $log->warning("Sweeper: recovered {$filepath} by spooling for retry");
            StateStore::record($cfg, $filepath, 'spooled', [
                'source' => 'sweeper', 'job_id' => $jobId, 'last_error' => $error,
            ]);
        } else {
            $log->error("Sweeper: upload of {$filepath} failed for good: {$error}");
            StateStore::record($cfg, $filepath, 'failed', ['source' => 'sweeper', 'last_error' => $error]);
        }
        return $outcome;
    }

    public static function sweepOnce(array $cfg, Logger $log, bool $dryRun = false): array
    {
        $excludes = self::compileExcludes($cfg);
        $minAge = $cfg['watcher']['min_file_age_seconds'];
        $now = time();
        $store = StateStore::create($cfg);
        $queue = Queue::create($cfg);

        $summary = [
            'ok' => 0, 'ignored' => 0, 'recovered_uploaded' => 0, 'recovered_spooled' => 0,
            'recovered_failed' => 0, 'too_fresh' => 0, 'problems' => [],
        ];

        foreach (self::iterCandidateFiles($cfg) as $filepath) {
            $name = basename($filepath);
            $mtime = @filemtime($filepath);
            if ($mtime === false) {
                continue;
            }
            if ($now - $mtime < $minAge) {
                $summary['too_fresh']++;
                continue;
            }

            $excluded = false;
            foreach ($excludes as $pattern) {
                if (@preg_match($pattern, $name) === 1) {
                    $excluded = true;
                    break;
                }
            }
            if ($excluded) {
                if (!$dryRun) {
                    StateStore::record($cfg, $filepath, 'ignored', ['source' => 'sweeper']);
                }
                $summary['ignored']++;
                continue;
            }

            if (!str_starts_with($name, self::STEREO_PREFIX) || strtolower(pathinfo($name, PATHINFO_EXTENSION)) !== 'wav') {
                continue;
            }

            $entry = $store->get($filepath);
            $actionNeeded = self::needsAction($cfg, $entry, $queue);

            if (!$actionNeeded) {
                $summary['ok']++;
                continue;
            }

            if ($dryRun) {
                $summary['problems'][] = ['file' => $filepath, 'status' => $entry['status'] ?? 'untracked'];
                continue;
            }

            $outcome = self::attemptRecovery($cfg, $filepath, $entry, $log);
            $summary["recovered_{$outcome}"]++;
        }

        if (!$dryRun) {
            $store->setLastSweep((float) $now);
            $removed = $store->pruneOkOlderThan($cfg['state']['retention_days'] * 86400);
            if ($removed) {
                $log->info("Sweeper: pruned {$removed} old resolved state entries");
            }
            $uploadedDir = $cfg['post_upload']['move_dir'] ?? '';
            if (($cfg['post_upload']['on_success'] ?? '') === 'move' && $uploadedDir !== '' && is_dir($uploadedDir)) {
                $cutoff = $now - ((int) $cfg['state']['retention_days'] * 86400);
                $deleted = 0;
                foreach (new \DirectoryIterator($uploadedDir) as $file) {
                    if ($file->isFile() && $file->getMTime() < $cutoff && @unlink($file->getPathname())) {
                        $deleted++;
                    }
                }
                if ($deleted) {
                    $log->info("Sweeper: deleted {$deleted} expired uploaded files");
                }
            }
        }

        return $summary;
    }
}
