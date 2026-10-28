<?php
/**
 * StateStore.php - per-call status tracking.
 *
 * Replaces state_store.py's single-JSON-blob design (plan.md §2.3) with a
 * SQLite `calls` table opened in WAL mode: one row per call, indexed on
 * status and last_updated_epoch, so a status transition is a single
 * indexed UPDATE/INSERT instead of a whole-file read-modify-rewrite.
 *
 * Falls back automatically to the original JSON-file behaviour when
 * pdo_sqlite isn't available (plan.md §3.5) - this is a performance
 * upgrade path, not a new hard requirement.
 */

namespace Engine;

interface StateStoreInterface
{
    public function get(string $filepath): ?array;
    public function upsert(string $filepath, array $fields): array;
    public function allEntries(): array;
    public function setLastSweep(?float $epoch = null): void;
    public function getLastSweep(): float;
    public function pruneOkOlderThan(int $seconds): int;
}

class StateStore
{
    const TERMINAL_OK_STATUSES = ['uploaded', 'ignored'];

    /**
     * Factory: returns the SQLite-backed implementation when pdo_sqlite
     * is available, otherwise the JSON-file fallback. Both implement
     * StateStoreInterface with identical semantics.
     */
    public static function create(array $cfg): StateStoreInterface
    {
        if (self::sqliteAvailable()) {
            try {
                return new SqliteStateStore(Config::sqlitePath($cfg));
            } catch (\Throwable $e) {
                // Fall through to JSON on any runtime failure (e.g. the
                // directory isn't writable, extension present but broken).
            }
        }
        return new JsonStateStore($cfg['state']['state_file']);
    }

    public static function sqliteAvailable(): bool
    {
        return extension_loaded('pdo_sqlite') && in_array('sqlite', \PDO::getAvailableDrivers(), true);
    }

    /** Convenience wrapper matching the old Python `record()` helper. */
    public static function record(array $cfg, string $filepath, string $status, array $fields = []): array
    {
        $store = self::create($cfg);
        $fields['status'] = $status;
        return $store->upsert($filepath, $fields);
    }

    public static function jobIdFromPath(string $jobPath): string
    {
        return pathinfo($jobPath, PATHINFO_FILENAME);
    }
}

/**
 * SQLite-backed implementation. One row per call, primary-keyed on the
 * absolute recording path.
 */
class SqliteStateStore implements StateStoreInterface
{
    private \PDO $pdo;

    public function __construct(string $sqlitePath)
    {
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
            CREATE TABLE IF NOT EXISTS calls (
                filepath TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                metadata TEXT,
                source TEXT,
                job_id TEXT,
                last_error TEXT,
                first_seen_epoch REAL NOT NULL,
                last_updated_epoch REAL NOT NULL
            )
        SQL);
        $this->pdo->exec('CREATE INDEX IF NOT EXISTS idx_calls_status ON calls(status)');
        $this->pdo->exec('CREATE INDEX IF NOT EXISTS idx_calls_last_updated ON calls(last_updated_epoch)');
        $this->pdo->exec(<<<SQL
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        SQL);
    }

    public function get(string $filepath): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM calls WHERE filepath = :fp');
        $stmt->execute(['fp' => realpath($filepath) ?: $filepath]);
        $row = $stmt->fetch(\PDO::FETCH_ASSOC);
        if (!$row) {
            return null;
        }
        return $this->rowToEntry($row);
    }

    public function upsert(string $filepath, array $fields): array
    {
        $key = realpath($filepath) ?: $filepath;
        $now = microtime(true);

        $existing = $this->get($key);
        $entry = $existing ?? ['first_seen_epoch' => $now];
        foreach ($fields as $k => $v) {
            $entry[$k] = $v;
        }
        $entry['last_updated_epoch'] = $now;
        $entry['first_seen_epoch'] = $entry['first_seen_epoch'] ?? $now;

        $params = [
            'fp' => $key,
            'status' => $entry['status'] ?? 'discovered',
            'metadata' => isset($entry['metadata']) ? json_encode($entry['metadata']) : null,
            'source' => $entry['source'] ?? null,
            'job_id' => $entry['job_id'] ?? null,
            'last_error' => $entry['last_error'] ?? null,
            'first_seen' => $entry['first_seen_epoch'],
            'last_updated' => $entry['last_updated_epoch'],
        ];
        $this->pdo->beginTransaction();
        try {
            $insert = $this->pdo->prepare(<<<SQL
                INSERT OR IGNORE INTO calls
                    (filepath, status, metadata, source, job_id, last_error, first_seen_epoch, last_updated_epoch)
                VALUES
                    (:fp, :status, :metadata, :source, :job_id, :last_error, :first_seen, :last_updated)
SQL);
            $insert->execute($params);
            $update = $this->pdo->prepare(<<<SQL
                UPDATE calls SET
                    status = :status,
                    metadata = :metadata,
                    source = :source,
                    job_id = :job_id,
                    last_error = :last_error,
                    last_updated_epoch = :last_updated
                WHERE filepath = :fp
SQL);
            $update->execute([
                'fp' => $params['fp'],
                'status' => $params['status'],
                'metadata' => $params['metadata'],
                'source' => $params['source'],
                'job_id' => $params['job_id'],
                'last_error' => $params['last_error'],
                'last_updated' => $params['last_updated'],
            ]);
            $this->pdo->commit();
        } catch (\Throwable $exc) {
            if ($this->pdo->inTransaction()) {
                $this->pdo->rollBack();
            }
            throw $exc;
        }

        return $entry;
    }

    public function allEntries(): array
    {
        $out = [];
        foreach ($this->pdo->query('SELECT * FROM calls') as $row) {
            $out[$row['filepath']] = $this->rowToEntry($row);
        }
        return $out;
    }

    public function setLastSweep(?float $epoch = null): void
    {
        $epoch = $epoch ?? microtime(true);
        $stmt = $this->pdo->prepare('INSERT OR REPLACE INTO meta (key, value) VALUES (:k, :v)');
        $stmt->execute(['k' => 'last_sweep_epoch', 'v' => (string) $epoch]);
    }

    public function getLastSweep(): float
    {
        $stmt = $this->pdo->prepare('SELECT value FROM meta WHERE key = :k');
        $stmt->execute(['k' => 'last_sweep_epoch']);
        $val = $stmt->fetchColumn();
        return $val !== false ? (float) $val : 0.0;
    }

    public function pruneOkOlderThan(int $seconds): int
    {
        $cutoff = microtime(true) - $seconds;
        $placeholders = implode(',', array_fill(0, count(StateStore::TERMINAL_OK_STATUSES), '?'));
        $stmt = $this->pdo->prepare(
            "DELETE FROM calls WHERE status IN ({$placeholders}) AND last_updated_epoch < ?"
        );
        $stmt->execute([...StateStore::TERMINAL_OK_STATUSES, $cutoff]);
        return $stmt->rowCount();
    }

    private function rowToEntry(array $row): array
    {
        $entry = [
            'status' => $row['status'],
            'source' => $row['source'],
            'job_id' => $row['job_id'],
            'last_error' => $row['last_error'],
            'first_seen_epoch' => (float) $row['first_seen_epoch'],
            'last_updated_epoch' => (float) $row['last_updated_epoch'],
        ];
        if ($row['metadata'] !== null) {
            $entry['metadata'] = json_decode($row['metadata'], true);
        }
        return array_filter($entry, fn($v) => $v !== null);
    }
}

/**
 * JSON-file fallback, functionally identical to the original Python
 * state_store.py: one JSON blob, flock-guarded, full read-modify-rewrite
 * per call. Kept as a real, exercised code path (not just a stub) since
 * it's the automatic fallback whenever pdo_sqlite is unavailable.
 */
class JsonStateStore implements StateStoreInterface
{
    private string $path;
    private string $lockPath;

    public function __construct(string $path)
    {
        $this->path = $path;
        $this->lockPath = $path . '.lock';
    }

    private function withLock(callable $fn)
    {
        $dir = dirname($this->path);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }
        $fh = fopen($this->lockPath, 'c+');
        if ($fh === false) {
            throw new \RuntimeException("Could not open lock file: {$this->lockPath}");
        }
        try {
            flock($fh, LOCK_EX);
            $data = $this->load();
            $result = $fn($data);
            $this->save($data);
            return $result;
        } finally {
            flock($fh, LOCK_UN);
            fclose($fh);
        }
    }

    private function load(): array
    {
        if (is_file($this->path)) {
            $raw = file_get_contents($this->path);
            $decoded = $raw !== false ? json_decode($raw, true) : null;
            if (is_array($decoded)) {
                $decoded += ['files' => [], 'last_sweep_epoch' => 0];
                return $decoded;
            }
        }
        return ['files' => [], 'last_sweep_epoch' => 0];
    }

    private function save(array $data): void
    {
        $tmp = $this->path . '.tmp';
        file_put_contents($tmp, json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
        rename($tmp, $this->path);
    }

    public function get(string $filepath): ?array
    {
        return $this->withLock(function (&$data) use ($filepath) {
            $key = realpath($filepath) ?: $filepath;
            return $data['files'][$key] ?? null;
        });
    }

    public function upsert(string $filepath, array $fields): array
    {
        return $this->withLock(function (&$data) use ($filepath, $fields) {
            $key = realpath($filepath) ?: $filepath;
            $entry = $data['files'][$key] ?? ['status' => 'discovered', 'first_seen_epoch' => microtime(true)];
            foreach ($fields as $k => $v) {
                $entry[$k] = $v;
            }
            $entry['last_updated_epoch'] = microtime(true);
            $data['files'][$key] = $entry;
            return $entry;
        });
    }

    public function allEntries(): array
    {
        return $this->withLock(function (&$data) {
            return $data['files'];
        });
    }

    public function setLastSweep(?float $epoch = null): void
    {
        $this->withLock(function (&$data) use ($epoch) {
            $data['last_sweep_epoch'] = $epoch ?? microtime(true);
            return null;
        });
    }

    public function getLastSweep(): float
    {
        return $this->withLock(function (&$data) {
            return (float) ($data['last_sweep_epoch'] ?? 0);
        });
    }

    public function pruneOkOlderThan(int $seconds): int
    {
        return $this->withLock(function (&$data) use ($seconds) {
            $cutoff = microtime(true) - $seconds;
            $removed = 0;
            foreach (array_keys($data['files']) as $key) {
                $entry = $data['files'][$key];
                if (
                    in_array($entry['status'] ?? null, StateStore::TERMINAL_OK_STATUSES, true)
                    && ($entry['last_updated_epoch'] ?? 0) < $cutoff
                ) {
                    unset($data['files'][$key]);
                    $removed++;
                }
            }
            return $removed;
        });
    }
}
