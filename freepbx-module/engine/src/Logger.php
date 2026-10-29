<?php
/**
 * Logger.php - file logger (plus optional syslog) used by every engine process.
 *
 * Line format (kept compatible with the admin page's log viewer, which finds the
 * level with /\]\s+(DEBUG|INFO|WARNING|ERROR)\s/):
 *
 *   2026-10-29 10:15:02+0330 [1234] ERROR aru.service: Upload failed | code=SS-UPL-0401 http_status=401 uniqueid=1730...
 *
 * - The text before " | " is the human message; after it come logfmt key=value
 *   pairs ("code" first). Values are quoted when they contain spaces.
 * - Every message and value is redacted (API keys, passwords, bearer tokens,
 *   configured secrets) and stripped of control characters, so a hostile caller
 *   ID or server response cannot forge log lines or leak credentials.
 * - Phone-like fields are masked to their last 3 digits unless
 *   logging.mask_numbers is false.
 * - Rotation is size-based under an flock so the service, uploader hook and
 *   sweeper cannot rotate over each other; new files are created 0640.
 */

namespace Engine;

class Logger
{
    const LEVELS = ['DEBUG' => 10, 'INFO' => 20, 'WARNING' => 30, 'ERROR' => 40];
    const MAX_BYTES = 10 * 1024 * 1024;
    const KEEP_FILES = 5;
    const MAX_VALUE_LENGTH = 300;
    const NUMBER_KEYS = ['src', 'dst', 'caller', 'dialed', 'number', 'from', 'to', 'cid'];

    private string $name;
    private int $level;
    private ?string $logFile;
    private bool $useSyslog;
    private bool $maskNumbers;
    private bool $syslogOpen = false;
    /** @var string[] */
    private array $secrets = [];

    public function __construct(array $cfg, string $name = 'aru')
    {
        $this->name = $name;
        $logCfg = $cfg['logging'];
        $this->level = self::LEVELS[strtoupper((string) $logCfg['log_level'])] ?? self::LEVELS['INFO'];
        $this->logFile = $logCfg['log_file'] ?: null;
        $this->useSyslog = (bool) $logCfg['use_syslog'];
        $this->maskNumbers = !array_key_exists('mask_numbers', $logCfg) || (bool) $logCfg['mask_numbers'];
        foreach (['api_key', 'archive_password'] as $key) {
            $value = (string) ($cfg['general'][$key] ?? '');
            if (strlen($value) >= 6) {
                $this->secrets[] = $value;
            }
        }

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

    /** Removes credentials and control characters from free text. Safe to call from anywhere. */
    public static function redact(string $text, array $secrets = []): string
    {
        foreach ($secrets as $secret) {
            if ($secret !== '') {
                $text = str_replace($secret, '[REDACTED]', $text);
            }
        }
        $text = preg_replace('/sk_(?:live|test)_[A-Za-z0-9_\-]+/', '[REDACTED]', $text) ?? $text;
        $text = preg_replace('/(Authorization|X-API-Key|X-CBI-Archive-Password)\s*[:=]\s*[^\r\n"\'&]+/i', '$1: [REDACTED]', $text) ?? $text;
        $text = preg_replace('/\bBearer\s+[A-Za-z0-9._~+\/=\-]{8,}/i', 'Bearer [REDACTED]', $text) ?? $text;
        $text = preg_replace('/([?&](?:api_key|apikey|token|password|secret)=)[^&\s]+/i', '$1[REDACTED]', $text) ?? $text;
        $text = preg_replace('/[\r\n\t]+/', ' ', $text) ?? $text;
        return preg_replace('/[\x00-\x1f\x7f]/', '', $text) ?? $text;
    }

    public static function maskNumber(string $value): string
    {
        $digits = preg_replace('/\D/', '', $value) ?? '';
        if (strlen($digits) <= 3) {
            return $value === '' ? '' : '***';
        }
        return str_repeat('*', strlen($digits) - 3) . substr($digits, -3);
    }

    private function formatContext(array $ctx): string
    {
        $parts = [];
        if (isset($ctx['code'])) {
            $parts[] = 'code=' . self::redact((string) $ctx['code']);
            unset($ctx['code']);
        }
        foreach ($ctx as $key => $value) {
            if ($value === null || $value === '' || is_array($value) || is_object($value)) {
                continue;
            }
            $key = preg_replace('/[^a-z0-9_]/i', '_', (string) $key);
            if (is_bool($value)) {
                $text = $value ? 'true' : 'false';
            } else {
                $text = self::redact((string) $value, $this->secrets);
            }
            if ($this->maskNumbers && in_array(strtolower($key), self::NUMBER_KEYS, true)) {
                $text = self::maskNumber($text);
            }
            if (strlen($text) > self::MAX_VALUE_LENGTH) {
                $text = substr($text, 0, self::MAX_VALUE_LENGTH) . '...';
            }
            if ($text === '' || preg_match('/[\s"=]/', $text)) {
                $text = '"' . str_replace('"', "'", $text) . '"';
            }
            $parts[] = $key . '=' . $text;
        }
        return $parts ? ' | ' . implode(' ', $parts) : '';
    }

    private function rotateIfNeeded(): void
    {
        clearstatcache(true, (string) $this->logFile);
        if (!is_file($this->logFile) || filesize($this->logFile) <= self::MAX_BYTES) {
            return;
        }
        $lock = @fopen($this->logFile . '.lock', 'c');
        if ($lock === false || !flock($lock, LOCK_EX)) {
            return;
        }
        // Re-check under the lock: another process may have rotated while we waited.
        clearstatcache(true, $this->logFile);
        if (is_file($this->logFile) && filesize($this->logFile) > self::MAX_BYTES) {
            for ($i = self::KEEP_FILES - 1; $i >= 1; $i--) {
                $src = "{$this->logFile}.{$i}";
                if (is_file($src)) {
                    @rename($src, "{$this->logFile}." . ($i + 1));
                }
            }
            @rename($this->logFile, "{$this->logFile}.1");
        }
        flock($lock, LOCK_UN);
        fclose($lock);
    }

    private function log(string $level, string $message, array $ctx = []): void
    {
        if (self::LEVELS[$level] < $this->level) {
            return;
        }
        $message = self::redact($message, $this->secrets) . $this->formatContext($ctx);
        $line = sprintf('%s [%d] %s %s: %s', date('Y-m-d H:i:sO'), getmypid(), $level, $this->name, $message);

        $wrote = false;
        if ($this->logFile) {
            $this->rotateIfNeeded();
            $isNew = !is_file($this->logFile);
            $wrote = @file_put_contents($this->logFile, $line . "\n", FILE_APPEND | LOCK_EX) !== false;
            if ($wrote && $isNew) {
                @chmod($this->logFile, 0640);
            }
        }
        if ($this->syslogOpen) {
            // PHP 7.4 baseline - no match expression.
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

    public function debug(string $message, array $ctx = []): void
    {
        $this->log('DEBUG', $message, $ctx);
    }

    public function info(string $message, array $ctx = []): void
    {
        $this->log('INFO', $message, $ctx);
    }

    public function warning(string $message, array $ctx = []): void
    {
        $this->log('WARNING', $message, $ctx);
    }

    public function error(string $message, array $ctx = []): void
    {
        $this->log('ERROR', $message, $ctx);
    }

    /** Logs with the severity of a catalog code, e.g. $log->coded('SS-QUE-1004', 'Upload failed', [...]). */
    public function coded(string $code, string $message, array $ctx = []): void
    {
        $entry = ErrorCatalog::lookup($code);
        $severity = $entry['severity'] ?? 'error';
        $level = $severity === 'info' ? 'INFO' : ($severity === 'warning' ? 'WARNING' : 'ERROR');
        $this->log($level, $message, ['code' => $code] + $ctx);
    }

    /** Returns a \Closure suitable for passing as the $log callback elsewhere. */
    public function asClosure(string $level = 'INFO'): \Closure
    {
        return fn(string $message) => $this->log($level, $message);
    }
}
