<?php

namespace Engine;

class CdrSource
{
    private $db;
    private string $table;

    public function __construct($db, string $table)
    {
        if (!preg_match('/^[A-Za-z0-9_]+$/', $table)) {
            throw new \RuntimeException('Unsafe CDR table name');
        }
        $this->db = $db;
        $this->table = $table;
    }

    public static function connect(): self
    {
        static $source = null;
        if ($source instanceof self) {
            return $source;
        }
        $bootstrap = '/etc/freepbx.conf';
        if (!is_file($bootstrap)) {
            throw new \RuntimeException('FreePBX bootstrap not found at /etc/freepbx.conf');
        }
        require_once $bootstrap;
        $table = \FreePBX::Config()->get('CDRDBTABLENAME') ?: 'cdr';
        $db = \FreePBX::Cdr()->getCdrDbHandle();
        $db->exec("SET time_zone = 'SYSTEM'");
        return $source = new self($db, (string) $table);
    }

    public function diagnostics(): array
    {
        try {
            $columns = $this->db->query('SHOW COLUMNS FROM `' . $this->table . '`')->fetchAll(\PDO::FETCH_COLUMN);
            $required = ['calldate', 'src', 'dst', 'disposition', 'duration', 'uniqueid', 'linkedid', 'dcontext'];
            $missing = array_values(array_diff($required, $columns));
            $settings = [];
            $path = '/etc/asterisk/cdr.conf';
            if (is_readable($path)) {
                $contents = file_get_contents($path);
                $section = '';
                foreach (preg_split('/\R/', $contents) as $line) {
                    if (preg_match('/^\s*\[([^]]+)\]/', $line, $match)) {
                        $section = strtolower(trim($match[1]));
                    } elseif ($section === 'general' && preg_match('/^\s*(unanswered|congestion|canceldispositionenabled)\s*=\s*([^;#\s]+)/i', $line, $match)) {
                        $settings[strtolower($match[1])] = strtolower($match[2]);
                    }
                }
            }
            return [
                'available' => !$missing,
                'table' => $this->table,
                'missing_columns' => $missing,
                'cdr_settings' => $settings,
                'unanswered_ready' => ($settings['unanswered'] ?? null) === 'yes',
                'congestion_ready' => ($settings['congestion'] ?? null) === 'yes',
            ];
        } catch (\Throwable $exc) {
            return ['available' => false, 'table' => $this->table, 'error' => $exc->getMessage()];
        }
    }

    public function candidates(int $windowStart, int $afterEpoch, string $afterLinkedId, int $beforeEpoch, int $limit = 500): array
    {
        $this->assertColumns(['calldate', 'linkedid']);
        $sql = 'SELECT linkedid, MAX(UNIX_TIMESTAMP(calldate)) AS latest_epoch FROM `' . $this->table . '` '
            . 'WHERE linkedid IS NOT NULL AND linkedid <> \'\' AND calldate >= FROM_UNIXTIME(:after) '
            . 'AND calldate <= FROM_UNIXTIME(:before) GROUP BY linkedid '
            . 'HAVING latest_epoch >= :window_start AND latest_epoch <= :before_group '
            . 'AND (latest_epoch > :page_after_epoch OR (latest_epoch = :page_after_epoch AND linkedid > :after_linkedid)) '
            . 'ORDER BY latest_epoch ASC, linkedid ASC LIMIT ' . max(1, min(2000, $limit));
        $stmt = $this->db->prepare($sql);
        $stmt->execute([
            'after' => $windowStart,
            'before' => $beforeEpoch,
            'window_start' => $windowStart,
            'before_group' => $beforeEpoch,
            'page_after_epoch' => $afterEpoch,
            'after_linkedid' => $afterLinkedId,
        ]);
        return $stmt->fetchAll(\PDO::FETCH_ASSOC);
    }

    public function group(string $linkedid): array
    {
        $this->assertColumns(['calldate', 'src', 'dst', 'disposition', 'duration', 'uniqueid', 'linkedid', 'dcontext']);
        $sql = 'SELECT calldate, UNIX_TIMESTAMP(calldate) AS call_epoch, src, dst, disposition, duration, uniqueid, linkedid, dcontext '
            . 'FROM `' . $this->table . '` WHERE linkedid = :linkedid '
            . 'ORDER BY calldate ASC, uniqueid ASC';
        $stmt = $this->db->prepare($sql);
        $stmt->execute(['linkedid' => $linkedid]);
        return $stmt->fetchAll(\PDO::FETCH_ASSOC);
    }

    private function assertColumns(array $required): void
    {
        $columns = $this->db->query('SHOW COLUMNS FROM `' . $this->table . '`')->fetchAll(\PDO::FETCH_COLUMN);
        $missing = array_values(array_diff($required, $columns));
        if ($missing) {
            throw new \RuntimeException('CDR table is missing required columns: ' . implode(', ', $missing));
        }
    }
}
