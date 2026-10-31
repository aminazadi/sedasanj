<?php
namespace Engine;

class IssabelSettings
{
    public static function defaults(): array
    {
        $cfg = Config::DEFAULTS;
        $cfg['watcher']['watch_dir'] = '/var/spool/asterisk-recording-uploader/recordings';
        $cfg['archive']['format'] = 'wav';
        return $cfg;
    }

    public static function write(array $cfg, string $path): void
    {
        $ini = '';
        foreach ($cfg as $section => $values) {
            if (!isset(Config::DEFAULTS[$section]) || !is_array($values)) {
                throw new \RuntimeException('SS-CFG-1003');
            }
            $ini .= '[' . $section . "]\n";
            foreach ($values as $key => $value) {
                if (!array_key_exists($key, Config::DEFAULTS[$section]) || !is_scalar($value)) {
                    throw new \RuntimeException('SS-CFG-1003');
                }
                // Encode strings to prevent INI interpolation, quoting and newline ambiguity.
                if (is_string($value)) {
                    if (strlen($value) > 8192 || strpos($value, "\0") !== false) { throw new \RuntimeException('SS-CFG-1003'); }
                    $ini .= $key . '_b64 = "' . base64_encode($value) . "\"\n";
                } else {
                    $ini .= $key . ' = ' . (is_bool($value) ? ($value ? 'true' : 'false') : (string) $value) . "\n";
                }
            }
        }
        self::atomic($path, $ini, 0640);
    }

    public static function atomic(string $path, string $body, int $mode = 0640): void
    {
        $tmp = tempnam(dirname($path), '.sedasanj-');
        if ($tmp === false) { throw new \RuntimeException('SS-SYS-1007'); }
        try {
            if (file_put_contents($tmp, $body, LOCK_EX) === false || !chmod($tmp, $mode) || !rename($tmp, $path)) {
                throw new \RuntimeException('SS-SYS-1007');
            }
        } finally { if (is_file($tmp)) { unlink($tmp); } }
    }

    public static function validate(array $input, array $previous): array
    {
        $cfg = $previous;
        foreach ($input as $section => $values) {
            if (!isset($cfg[$section]) || !is_array($values)) { throw new \RuntimeException('SS-CFG-1003'); }
            foreach ($values as $key => $value) {
                if (!array_key_exists($key, $cfg[$section]) || !is_scalar($value)) { throw new \RuntimeException('SS-CFG-1003'); }
                if (in_array($key, ['api_key', 'archive_password'], true) && $value === '') { continue; }
                $default = Config::DEFAULTS[$section][$key];
                if (is_bool($default)) {
                    if (!in_array($value, [true, false, '0', '1'], true)) { throw new \RuntimeException('SS-CFG-1003'); }
                    $value = $value === true || $value === '1';
                } elseif (is_int($default)) {
                    if (filter_var($value, FILTER_VALIDATE_INT) === false || (int) $value < 0 || (int) $value > 31536000) { throw new \RuntimeException('SS-CFG-1003'); }
                    $value = (int) $value;
                } else { $value = (string) $value; }
                $cfg[$section][$key] = $value;
            }
        }
        if (!filter_var($cfg['general']['endpoint'], FILTER_VALIDATE_URL)
            || parse_url($cfg['general']['endpoint'], PHP_URL_SCHEME) !== 'https'
            || parse_url($cfg['general']['endpoint'], PHP_URL_USER) !== null
            || substr($cfg['general']['endpoint'], -strlen('/v1/ingest/calls')) !== '/v1/ingest/calls') { throw new \RuntimeException('SS-CFG-1004'); }
        if (!in_array($cfg['upload']['format'], ['wav', 'gzip', 'zip'], true)
            || !in_array($cfg['archive']['format'], ['wav', 'gsm', 'mp3', 'ogg', 'opus'], true)
            || !in_array($cfg['logging']['log_level'], ['DEBUG', 'INFO', 'WARNING', 'ERROR'], true)
            || !in_array($cfg['post_upload']['on_success'], ['move', 'delete', 'keep'], true)
            || $cfg['watcher']['watch_dir'] !== self::defaults()['watcher']['watch_dir']
            || $cfg['missed_calls']['poll_interval_seconds'] < 10
            || $cfg['general']['timeout_seconds'] < 1) { throw new \RuntimeException('SS-CFG-1003'); }
        foreach ($cfg as $section => $values) {
            foreach ($values as $key => $value) {
                if (is_string($value) && (strpos($value, "\0") !== false || preg_match('/[\r\n]/', $value))) { throw new \RuntimeException('SS-CFG-1003'); }
                if (preg_match('/(_dir|_file)$/', $key) && ($value === '' || $value[0] !== '/' || strpos($value, '/../') !== false)) { throw new \RuntimeException('SS-CFG-1003'); }
            }
        }
        if (@preg_match('~' . str_replace('~', '\\~', $cfg['watcher']['filename_pattern']) . '~', '') === false) { throw new \RuntimeException('SS-CFG-1003'); }
        return $cfg;
    }
}
