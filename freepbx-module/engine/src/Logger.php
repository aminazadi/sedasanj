<?php
/**
 * Logger.php - minimal logging, mirroring common.setup_logging(): a
 * rotating-ish file handler (simple size-check rotation) plus optional
 * syslog, falling back to stderr if neither is writable.
 */

namespace Engine;

class Logger
{
    const LEVELS = ['DEBUG' => 10, 'INFO' => 20, 'WARNING' => 30, 'ERROR' => 40];

    private string $name;
    private int $level;
    private ?string $logFile;
    private bool $useSyslog;
    private bool $syslogOpen = false;

    public function __construct(array $cfg, string $name = 'aru')
    {
        $this->name = $name;
        $logCfg = $cfg['logging'];
        $this->level = self::LEVELS[strtoupper($logCfg['log_level'])] ?? self::LEVELS['INFO'];
        $this->logFile = $logCfg['log_file'] ?: null;
        $this->useSyslog = (bool) $logCfg['use_syslog'];

        if ($this->logFile) {
            $dir = dirname($this->logFile);
            if (!is_dir($dir)) {
                @mkdir($dir, 0755, true);
            }
        }
        if ($this->useSyslog) {
            $this->syslogOpen = openlog($this->name, LOG_PID, LOG_USER);
        }
    }

    private function log(string $level, string $message): void
    {
        if (self::LEVELS[$level] < $this->level) {
            return;
        }
        $line = sprintf('%s [%d] %s %s: %s', date('Y-m-d H:i:s'), getmypid(), $level, $this->name, $message);

        $wrote = false;
        if ($this->logFile) {
            // Simple size-based rotation: if the file exceeds 10 MiB,
            // rotate it aside before appending (a lightweight stand-in
            // for RotatingFileHandler's maxBytes=10MiB, backupCount=5).
            if (is_file($this->logFile) && filesize($this->logFile) > 10 * 1024 * 1024) {
                for ($i = 4; $i >= 1; $i--) {
                    $src = "{$this->logFile}.{$i}";
                    $dst = "{$this->logFile}." . ($i + 1);
                    if (is_file($src)) {
                        @rename($src, $dst);
                    }
                }
                @rename($this->logFile, "{$this->logFile}.1");
            }
            $wrote = @file_put_contents($this->logFile, $line . "\n", FILE_APPEND | LOCK_EX) !== false;
        }
        if ($this->syslogOpen) {
            // PHP 7.4 target baseline (plan.md §3.1) - no match expression
            // (PHP 8.0+ only). A plain switch is the 7.4-safe equivalent.
            switch ($level) {
                case 'DEBUG':
                    $prio = LOG_DEBUG;
                    break;
                case 'INFO':
                    $prio = LOG_INFO;
                    break;
                case 'WARNING':
                    $prio = LOG_WARNING;
                    break;
                default:
                    $prio = LOG_ERR;
                    break;
            }
            syslog($prio, "{$level} {$this->name}: {$message}");
            $wrote = true;
        }
        if (!$wrote) {
            fwrite(STDERR, $line . "\n");
        }
    }

    public function debug(string $message): void
    {
        $this->log('DEBUG', $message);
    }

    public function info(string $message): void
    {
        $this->log('INFO', $message);
    }

    public function warning(string $message): void
    {
        $this->log('WARNING', $message);
    }

    public function error(string $message): void
    {
        $this->log('ERROR', $message);
    }

    /** Returns a \Closure suitable for passing as the $log callback elsewhere. */
    public function asClosure(string $level = 'INFO'): \Closure
    {
        return fn(string $message) => $this->log($level, $message);
    }
}
