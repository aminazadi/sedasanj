<?php
namespace Engine\Host;

class Issabel implements Adapter
{
    private array $config;

    public function __construct(array $config)
    {
        $this->config = $config;
    }

    public function cdr(): array
    {
        $cfg = $this->config['cdr'] ?? [];
        foreach (['host', 'database', 'table', 'user', 'password'] as $key) {
            if (!isset($cfg[$key]) || !is_string($cfg[$key])) {
                throw new \RuntimeException('SS-CDR-1003: Run Issabel activation to refresh CDR access.');
            }
        }
        foreach (['database', 'table'] as $key) {
            if (!preg_match('/^[A-Za-z0-9_]+$/', $cfg[$key])) {
                throw new \RuntimeException('SS-CDR-1002: Correct the CDR database/table in PBX settings.');
            }
        }
        if (!preg_match('/^[A-Za-z0-9.:-]+$/', $cfg['host'])) {
            throw new \RuntimeException('SS-CDR-1003: Correct the CDR host in PBX settings.');
        }
        try {
            $pdo = new \PDO('mysql:host=' . $cfg['host'] . ';port=' . (int) ($cfg['port'] ?? 3306)
                . ';dbname=' . $cfg['database'] . ';charset=utf8mb4', $cfg['user'], $cfg['password'], [
                    \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
                    \PDO::ATTR_EMULATE_PREPARES => false,
                    \PDO::ATTR_TIMEOUT => 5,
                ]);
            return [$pdo, $cfg['table']];
        } catch (\PDOException $exception) {
            throw new \RuntimeException('SS-CDR-1003: Check MariaDB access and re-run activation.');
        }
    }

    public function extensions(): array
    {
        return $this->config['extensions'] ?? [];
    }
}
