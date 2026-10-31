<?php
/**
 * Config.php - single source of truth for default settings.
 *
 * Replaces three previously-duplicated locations (Recuploader::defaults(),
 * config/config.ini.example, common.load_config()'s fallback values - see
 * plan.md §2.5 / §3.6) with one PHP array that every frontend and every
 * engine entry point reads directly. config/config.ini.example is generated
 * from DEFAULTS at release time rather than hand-maintained in parallel.
 *
 * No FreePBX classes, no \FreePBX_Helpers/\BMO, no fwconsole, no KVStore -
 * this file only knows about a plain config.ini (engine/config §3.4).
 */

namespace Engine;

class ConfigError extends \RuntimeException
{
}

class Config
{
    const DEFAULT_CONFIG_PATH = '/etc/asterisk-recording-uploader/config.ini';

    // Default ingest endpoint (Sedasanj / CBI Call Ingest API).
    const DEFAULT_ENDPOINT = 'https://api.sedasanj.ir/v1/ingest/calls';

    // /v1/ingest/calls limits (see endpoint docs):
    //   - compressed upload <= 512 MiB
    //   - extracted WAV    <= 512 MiB
    //   - max compression ratio 100:1
    const MAX_COMPRESSED_BYTES = 512 * 1024 * 1024;

    // Form fields the ingest API marks as required. "file" is handled
    // separately because it's a multipart file part, not a regular value.
    const REQUIRED_INGEST_FIELDS = [
        'asterisk_uniqueid',
        'caller_number',
        'dialed_number',
        'started_at',
        'ended_at',
    ];

    /**
     * The single source of truth for every default value. Keyed the same
     * way as the parsed config array returned by load(): [section][key].
     */
    const DEFAULTS = [
        'general' => [
            'endpoint' => self::DEFAULT_ENDPOINT,
            'api_key' => '',
            'api_key_b64' => '',
            'auth_header' => 'Authorization',
            'auth_scheme' => 'Bearer',
            // If set, staged uploads become an AES-256 passworded ZIP and
            // the X-CBI-Archive-Password header is sent automatically.
            // Leave empty to use gzip (upload.gzip=true) or raw uploads.
            'archive_password' => '',
            'archive_password_b64' => '',
            'verify_tls' => true,
            'timeout_seconds' => 60,
            'immediate_retries' => 2,
        ],
        'upload' => [
            'format' => 'gzip',
            'method' => 'POST_MULTIPART',
            'file_field_name' => 'file',
            // "form_fields" is the only mode the ingest API supports.
            // "json_field" is kept for compatibility with pre-existing
            // deployments but will not work against /v1/ingest/calls.
            'metadata_mode' => 'form_fields',
            'metadata_json_field_name' => 'metadata',
            'extra_headers' => '',
            // Used only when general.archive_password is empty. When a
            // ZIP password is configured, ZIP packaging takes precedence
            // and this flag is ignored.
            'gzip' => true,
        ],
        'post_upload' => [
            'on_success' => 'move',
            'move_dir' => '/var/spool/asterisk-recording-uploader/uploaded',
        ],
        'archive' => [
            'format' => 'gsm',
        ],
        'watcher' => [
            'watch_dir' => '/var/spool/asterisk/monitor',
            // Stored WITHOUT PCRE delimiters (matches the raw Python `re`
            // pattern format used by the old config.ini) - callers wrap it
            // with delimiters at the point of use; see Sweeper::toPcre().
            'filename_pattern' =>
                '^(?P<exten>[^-]+)-(?P<date>\d{8})-(?P<time>\d{6})-(?P<uniqueid>[\d.]+)\.(?P<ext>wav|mp3|gsm)$',
            'state_file' => '/var/lib/asterisk-recording-uploader/watcher_state.json',
            'min_file_age_seconds' => 3,
        ],
        'missed_calls' => [
            'enabled' => false,
            'poll_interval_seconds' => 30,
            'settle_seconds' => 15,
            'overlap_seconds' => 120,
            'cursor_file' => '/var/lib/asterisk-recording-uploader/missed-calls-cursor.json',
            'spool_dir' => '/var/spool/asterisk-recording-uploader/missed-calls/pending',
            'failed_dir' => '/var/spool/asterisk-recording-uploader/missed-calls/failed',
        ],
        'voicemail' => [
            'enabled' => false,
            'spool_dir' => '/var/spool/asterisk/voicemail',
            'folders' => 'INBOX,Old,Urgent,Work,Family,Friends',
            'mailbox_filter' => '',
            'backfill' => false,
            'sweep_interval_seconds' => 60,
            'audio_preference' => 'wav,WAV,gsm',
        ],
        'queue' => [
            'spool_dir' => '/var/spool/asterisk-recording-uploader/pending',
            'failed_dir' => '/var/spool/asterisk-recording-uploader/failed',
            'max_retries' => 100,
            'retry_base_seconds' => 30,
            'retry_max_seconds' => 3600,
            'credit_retry_seconds' => 3600,
            'config_retry_seconds' => 3600,
        ],
        'state' => [
            'state_file' => '/var/lib/asterisk-recording-uploader/state.json',
            // Used for both the JSON fallback state file and as the
            // filename base for the SQLite store (state.sqlite lives
            // alongside it - see StateStore::sqlitePathFor()).
            'sweep_interval_seconds' => 300,
            'stale_processing_seconds' => 600,
            'recursive_scan' => true,
            'exclude_patterns' => '^(recv_|trans_).*$',
            'retention_days' => 90,
        ],
        'logging' => [
            'log_file' => '/var/log/asterisk-recording-uploader/uploader.log',
            'log_level' => 'INFO',
            'use_syslog' => true,
            // Mask phone-like fields (src, dst, caller, ...) to their last 3 digits in log lines.
            'mask_numbers' => true,
        ],
    ];

    /**
     * Load and validate config.ini into the same nested-array shape as
     * DEFAULTS, with every value present (falling back to DEFAULTS for
     * anything the file doesn't set).
     *
     * @param string|null $path Defaults to $ARU_CONFIG env var, then
     *                          DEFAULT_CONFIG_PATH.
     * @throws ConfigError
     */
    public static function load(?string $path = null): array
    {
        $path = $path ?: (getenv('ARU_CONFIG') ?: self::DEFAULT_CONFIG_PATH);
        if (!is_file($path)) {
            throw new ConfigError("Config file not found: {$path}");
        }

        $parsed = parse_ini_file($path, true, INI_SCANNER_RAW);
        if ($parsed === false) {
            throw new ConfigError("Could not parse config file: {$path}");
        }

        $cfg = self::DEFAULTS;
        foreach ($cfg as $section => $keys) {
            if (!isset($parsed[$section]) || !is_array($parsed[$section])) {
                continue;
            }
            foreach ($keys as $key => $default) {
                if (!array_key_exists($key, $parsed[$section])) {
                    continue;
                }
                if (substr($key, -4) === '_b64') { continue; }
                $raw = $parsed[$section][$key];
                $cfg[$section][$key] = self::castLike($default, $raw);
            }
        }

        if (!isset($parsed['upload']['format'])) {
            if ($cfg['general']['archive_password'] !== '') {
                $cfg['upload']['format'] = 'zip';
            } elseif (!empty($cfg['upload']['gzip'])) {
                $cfg['upload']['format'] = 'gzip';
            } else {
                $cfg['upload']['format'] = 'wav';
            }
        }
        $encodedValues = [];
        foreach (self::DEFAULTS as $section => $keys) {
            $encodedValues[$section] = array_keys(array_filter($keys, 'is_string'));
        }
        foreach ($encodedValues as $section => $keys) {
            foreach ($keys as $key) {
                $encodedKey = $key . '_b64';
                $encoded = $parsed[$section][$encodedKey] ?? '';
                if ($encoded === '') {
                    continue;
                }
                $decoded = base64_decode((string) $encoded, true);
                if ($decoded === false) {
                    throw new ConfigError("{$section}.{$encodedKey} is not valid base64");
                }
                $cfg[$section][$key] = $decoded;
            }
        }
        if (!in_array($cfg['upload']['format'], ['wav', 'gzip', 'zip'], true)) {
            throw new ConfigError('upload.format must be wav, gzip, or zip');
        }

        // Back-compat: some older deployments used queue.dead_letter_dir
        // instead of queue.failed_dir.
        if (
            (!isset($parsed['queue']['failed_dir']) || $parsed['queue']['failed_dir'] === '')
            && isset($parsed['queue']['dead_letter_dir'])
        ) {
            $cfg['queue']['failed_dir'] = (string) $parsed['queue']['dead_letter_dir'];
        }

        if (empty($cfg['general']['endpoint'])) {
            throw new ConfigError('general.endpoint is required in config file');
        }

        return $cfg;
    }

    /**
     * Cast a raw ini string to match the type of the corresponding
     * default value (bool/int/string), mirroring configparser's
     * getboolean/getint/get behaviour.
     */
    private static function castLike($default, $raw)
    {
        if (is_bool($default)) {
            if (is_bool($raw)) {
                return $raw;
            }
            $s = strtolower(trim((string) $raw));
            return in_array($s, ['1', 'true', 'yes', 'on'], true);
        }
        if (is_int($default)) {
            return (int) $raw;
        }
        return (string) $raw;
    }

    /**
     * The SQLite database path for the state/queue store, derived from
     * state.state_file's directory (same directory today's JSON state
     * file lives in) - see StateStore/Queue §3.5.
     */
    public static function sqlitePath(array $cfg): string
    {
        $dir = dirname($cfg['state']['state_file']);
        return rtrim($dir, '/') . '/state.sqlite';
    }
}
