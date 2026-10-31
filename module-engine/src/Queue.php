<?php
/**
 * Queue.php - retry queue for failed uploads.
 *
 * Replaces one-json-file-per-job (queue_worker.py's 5s poll doing a full
 * os.listdir() + open + json-parse per file - plan.md §2.3) with a SQLite
 * `jobs` table indexed on next_attempt_epoch: the worker's tick becomes one
 * indexed `SELECT * FROM jobs WHERE next_attempt_epoch <= :now` instead of
 * scanning every file in the spool directory.
 *
 * The audio file itself always stays a plain file on disk in the spool
 * directory (queue.spool_dir) - only the bookkeeping moves into the
 * database. Falls back to one-file-per-job JSON when pdo_sqlite isn't
 * available, same as StateStore (§3.5).
 */

namespace Engine;

interface QueueInterface
{
    /** @return string job_id */
    public function spool(string $filepath, ?string $archivePath, array $metadata, string $errorMessage): string;
    public function dueJobs(): array; // list of job arrays, each with 'job_id'
    public function get(string $jobId): ?array;
    public function save(array $job): void;
    public function remove(string $jobId): void;
}

class Queue
{
    public static function jobId(string $filepath, array $metadata): string
    {
        $identity = (string) ($metadata['uniqueid'] ?? $metadata['asterisk_uniqueid'] ?? '');
        if ($identity === '') {
            $identity = (realpath($filepath) ?: $filepath) . ':' . (string) @filesize($filepath);
        }
        return substr(hash('sha256', $identity), 0, 40);
    }

    public static function create(array $cfg): QueueInterface
    {
        if (StateStore::sqliteAvailable()) {
            try {
                return new SqliteQueue(Config::sqlitePath($cfg), $cfg['queue']['spool_dir']);
            } catch (\Throwable $e) {
                // fall through
            }
        }
        return new JsonQueue($cfg['queue']['spool_dir']);
    }

    public static function backoffSeconds(array $cfg, int $attempts): int
    {
        $base = $cfg['queue']['retry_base_seconds'];
        $cap = $cfg['queue']['retry_max_seconds'];
        return (int) min($cap, $base * (2 ** max(0, $attempts - 1)));
    }

    /**
     * One-time migration of any JSON job files sitting in the spool
     * directory into the SQLite `jobs` table (plan.md §3.5, upgrade path).
     * Safe to call every time the queue is opened - it only imports files
     * it hasn't already imported (tracked via meta.json_migrated_<file>).
     */
    public static function migrateJsonBacklog(array $cfg): int
    {
        if (!StateStore::sqliteAvailable()) {
            return 0;
        }
        $spoolDir = $cfg['queue']['spool_dir'];
        if (!is_dir($spoolDir)) {
            return 0;
        }
        try {
            $sqlite = new SqliteQueue(Config::sqlitePath($cfg), $spoolDir);
        } catch (\Throwable $e) {
            return 0;
        }
        $migrated = 0;
        foreach (glob(rtrim($spoolDir, '/') . '/*.json') ?: [] as $jsonPath) {
            $jobId = pathinfo($jsonPath, PATHINFO_FILENAME);
            if (preg_match('/^[0-9a-f]{40}$/', $jobId) !== 1) {
                continue;
            }
            if ($sqlite->get($jobId) !== null) {
                continue; // already migrated
            }
            $raw = @file_get_contents($jsonPath);
            $job = $raw !== false ? json_decode($raw, true) : null;
            if (!is_array($job)) {
                continue;
            }
            $job['job_id'] = $job['job_id'] ?? $jobId;
            $sqlite->save($job);
            @unlink($jsonPath);
            $migrated++;
        }
        return $migrated;
    }

    public static function recoverStagedOrphans(array $cfg): int
    {
        $spoolDir = $cfg['queue']['spool_dir'];
        if (!is_dir($spoolDir)) {
            return 0;
        }
        $queue = self::create($cfg);
        $recovered = 0;
        foreach (glob(rtrim($spoolDir, '/') . '/*.metadata.json') ?: [] as $sidecarPath) {
            $filepath = substr($sidecarPath, 0, -strlen('.metadata.json'));
            if (!is_file($filepath)) {
                continue;
            }
            $payload = json_decode((string) @file_get_contents($sidecarPath), true);
            if (!is_array($payload) || !is_array($payload['metadata'] ?? null)) {
                continue;
            }
            $metadata = $payload['metadata'];
            $jobId = self::jobId($filepath, $metadata);
            if ($queue->get($jobId) !== null) {
                continue;
            }
            $queue->spool(
                $filepath,
                isset($payload['archive_path']) ? (string) $payload['archive_path'] : null,
                $metadata,
                'recovered staged recording after interrupted processing'
            );
            $recovered++;
        }
        return $recovered;
    }
}

class SqliteQueue implements QueueInterface
{
    private \PDO $pdo;
    private string $spoolDir;

    public function __construct(string $sqlitePath, string $spoolDir)
    {
        $this->spoolDir = $spoolDir;
        $dir = dirname($sqlitePath);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }
        $this->pdo = new \PDO('sqlite:' . $sqlitePath);
        $this->pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $this->pdo->exec('PRAGMA busy_timeout=5000');
        $this->pdo->exec('PRAGMA journal_mode=WAL');
        $this->pdo->exec('PRAGMA synchronous=NORMAL');
        $this->migrate();
    }

    private function migrate(): void
    {
        $this->pdo->exec(<<<SQL
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                filepath TEXT NOT NULL,
                archive_path TEXT,
                metadata TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                next_attempt_epoch REAL NOT NULL,
                last_error TEXT,
                created_epoch REAL NOT NULL
            )
        SQL);
        $columns = $this->pdo->query('PRAGMA table_info(jobs)')->fetchAll(\PDO::FETCH_ASSOC);
        $names = array_column($columns, 'name');
        if (!in_array('status', $names, true)) {
            $this->pdo->exec("ALTER TABLE jobs ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'");
        }
        $this->pdo->exec('CREATE INDEX IF NOT EXISTS idx_jobs_next_attempt ON jobs(next_attempt_epoch)');
    }

    public function spool(string $filepath, ?string $archivePath, array $metadata, string $errorMessage): string
    {
        if (!is_dir($this->spoolDir)) {
            mkdir($this->spoolDir, 0755, true);
        }
        $jobId = Queue::jobId($filepath, $metadata);
        $job = [
            'job_id' => $jobId,
            'filepath' => realpath($filepath) ?: $filepath,
            'archive_path' => $archivePath ? (realpath($archivePath) ?: $archivePath) : null,
            'metadata' => $metadata,
            'attempts' => 0,
            'status' => 'pending',
            'next_attempt_epoch' => microtime(true),
            'last_error' => $errorMessage,
            'created_epoch' => microtime(true),
        ];
        $this->save($job);
        return $jobId;
    }

    public function dueJobs(): array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM jobs WHERE next_attempt_epoch <= :now ORDER BY next_attempt_epoch ASC');
        $stmt->execute(['now' => microtime(true)]);
        $out = [];
        foreach ($stmt->fetchAll(\PDO::FETCH_ASSOC) as $row) {
            $out[] = $this->rowToJob($row);
        }
        return $out;
    }

    public function get(string $jobId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM jobs WHERE job_id = :id');
        $stmt->execute(['id' => $jobId]);
        $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        return $row ? $this->rowToJob($row) : null;
    }

    public function save(array $job): void
    {
        $params = [
            'job_id' => $job['job_id'],
            'filepath' => $job['filepath'],
            'archive_path' => $job['archive_path'] ?? null,
            'metadata' => json_encode($job['metadata'] ?? []),
            'attempts' => $job['attempts'] ?? 0,
            'status' => $job['status'] ?? 'pending',
            'next_attempt' => $job['next_attempt_epoch'] ?? microtime(true),
            'last_error' => $job['last_error'] ?? null,
            'created' => $job['created_epoch'] ?? microtime(true),
        ];
        $this->pdo->beginTransaction();
        try {
            $insert = $this->pdo->prepare(<<<SQL
                INSERT OR IGNORE INTO jobs
                    (job_id, filepath, archive_path, metadata, attempts, status, next_attempt_epoch, last_error, created_epoch)
                VALUES
                    (:job_id, :filepath, :archive_path, :metadata, :attempts, :status, :next_attempt, :last_error, :created)
SQL);
            $insert->execute($params);
            $update = $this->pdo->prepare(<<<SQL
                UPDATE jobs SET
                    filepath = :filepath,
                    archive_path = :archive_path,
                    metadata = :metadata,
                    attempts = :attempts,
                    status = :status,
                    next_attempt_epoch = :next_attempt,
                    last_error = :last_error
                WHERE job_id = :job_id
SQL);
            $update->execute([
                'job_id' => $params['job_id'],
                'filepath' => $params['filepath'],
                'archive_path' => $params['archive_path'],
                'metadata' => $params['metadata'],
                'attempts' => $params['attempts'],
                'status' => $params['status'],
                'next_attempt' => $params['next_attempt'],
                'last_error' => $params['last_error'],
            ]);
            $this->pdo->commit();
        } catch (\Throwable $exc) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $exc;
        }
    }

    public function remove(string $jobId): void
    {
        $stmt = $this->pdo->prepare('DELETE FROM jobs WHERE job_id = :id');
        $stmt->execute(['id' => $jobId]);
    }

    private function rowToJob(array $row): array
    {
        return [
            'job_id' => $row['job_id'],
            'filepath' => $row['filepath'],
            'archive_path' => $row['archive_path'],
            'metadata' => $row['metadata'] ? json_decode($row['metadata'], true) : [],
            'attempts' => (int) $row['attempts'],
            'status' => $row['status'] ?? 'pending',
            'next_attempt_epoch' => (float) $row['next_attempt_epoch'],
            'last_error' => $row['last_error'],
            'created_epoch' => (float) $row['created_epoch'],
        ];
    }
}

/**
 * JSON-file-per-job fallback, functionally identical to the original
 * Python behaviour (common.spool_job / list_spool_jobs / load_job /
 * save_job): one <job_id>.json file per retryable failure.
 */
class JsonQueue implements QueueInterface
{
    private string $spoolDir;

    public function __construct(string $spoolDir)
    {
        $this->spoolDir = $spoolDir;
    }

    private function pathFor(string $jobId): string
    {
        return rtrim($this->spoolDir, '/') . '/' . $jobId . '.json';
    }

    public function spool(string $filepath, ?string $archivePath, array $metadata, string $errorMessage): string
    {
        if (!is_dir($this->spoolDir)) {
            mkdir($this->spoolDir, 0755, true);
        }
        $jobId = Queue::jobId($filepath, $metadata);
        $job = [
            'job_id' => $jobId,
            'filepath' => realpath($filepath) ?: $filepath,
            'archive_path' => $archivePath ? (realpath($archivePath) ?: $archivePath) : null,
            'metadata' => $metadata,
            'attempts' => 0,
            'status' => 'pending',
            'next_attempt_epoch' => microtime(true),
            'last_error' => $errorMessage,
            'created_epoch' => microtime(true),
        ];
        $this->save($job);
        return $jobId;
    }

    public function dueJobs(): array
    {
        if (!is_dir($this->spoolDir)) {
            return [];
        }
        $now = microtime(true);
        $out = [];
        $files = glob(rtrim($this->spoolDir, '/') . '/*.json') ?: [];
        sort($files);
        foreach ($files as $path) {
            if (preg_match('/^[0-9a-f]{40}\.json$/', basename($path)) !== 1) {
                continue;
            }
            $raw = @file_get_contents($path);
            $job = $raw !== false ? json_decode($raw, true) : null;
            if (!is_array($job) || ($job['job_id'] ?? null) !== pathinfo($path, PATHINFO_FILENAME)) {
                continue;
            }
            if (($job['next_attempt_epoch'] ?? 0) <= $now) {
                $out[] = $job;
            }
        }
        return $out;
    }

    public function get(string $jobId): ?array
    {
        $path = $this->pathFor($jobId);
        if (!is_file($path)) {
            return null;
        }
        $raw = file_get_contents($path);
        $job = $raw !== false ? json_decode($raw, true) : null;
        return is_array($job) ? $job : null;
    }

    public function save(array $job): void
    {
        if (!is_dir($this->spoolDir)) {
            mkdir($this->spoolDir, 0755, true);
        }
        $path = $this->pathFor($job['job_id']);
        $tmp = $path . '.tmp.' . getmypid();
        if (file_put_contents($tmp, json_encode($job, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), LOCK_EX) === false
            || !@rename($tmp, $path)) {
            @unlink($tmp);
            throw new \RuntimeException("Could not atomically save queue job {$path}");
        }
    }

    public function remove(string $jobId): void
    {
        @unlink($this->pathFor($jobId));
    }
}
