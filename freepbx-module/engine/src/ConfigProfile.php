<?php

namespace Engine;

class ConfigProfileError extends \RuntimeException
{
}

class ConfigProfile
{
    const SCHEMA = 'sedasanj.freepbx.recuploader.config';
    const VERSION = 1;
    const MAX_BYTES = 65536;

    private static function requireKeys(array $value, array $allowed, string $label): void
    {
        $unknown = array_diff(array_keys($value), $allowed);
        if ($unknown) {
            throw new ConfigProfileError($label . ' contains unknown key(s): ' . implode(', ', $unknown));
        }
        $missing = array_diff($allowed, array_keys($value));
        if ($missing) {
            throw new ConfigProfileError($label . ' is missing key(s): ' . implode(', ', $missing));
        }
    }

    private static function integer($value, int $min, int $max, string $label): string
    {
        if (!is_int($value) || $value < $min || $value > $max) {
            throw new ConfigProfileError("{$label} must be an integer between {$min} and {$max}");
        }
        return (string) $value;
    }

    private static function text($value, string $label, bool $allowEmpty = false): string
    {
        if (!is_string($value) || (!$allowEmpty && trim($value) === '') || strpos($value, "\0") !== false || preg_match('/[\r\n]/', $value)) {
            throw new ConfigProfileError("{$label} is invalid");
        }
        return $value;
    }

    private static function absolutePath($value, string $label): string
    {
        $path = self::text($value, $label);
        if ($path[0] !== '/' || strpos($path, '/../') !== false || substr($path, -3) === '/..') {
            throw new ConfigProfileError("{$label} must be an absolute normalized path");
        }
        return $path;
    }

    public static function parse(string $json): array
    {
        if (strlen($json) > self::MAX_BYTES) {
            throw new ConfigProfileError('Configuration file exceeds 64 KiB');
        }
        $doc = json_decode($json, true);
        if (!is_array($doc) || json_last_error() !== JSON_ERROR_NONE) {
            throw new ConfigProfileError('Configuration file is not valid JSON');
        }
        self::requireKeys($doc, ['schema', 'version', 'target', 'generated_at', 'profile', 'settings'], 'document');
        if (($doc['schema'] ?? null) !== self::SCHEMA || ($doc['version'] ?? null) !== self::VERSION) {
            throw new ConfigProfileError('Unsupported configuration schema or version');
        }
        if (($doc['target'] ?? null) !== 'freepbx-module') {
            throw new ConfigProfileError('Configuration target must be freepbx-module');
        }
        if (!is_array($doc['profile']) || !is_array($doc['settings'])) {
            throw new ConfigProfileError('profile and settings must be objects');
        }
        self::requireKeys($doc['profile'], ['api_key_id', 'api_key_prefix'], 'profile');
        $requiredSections = ['general', 'upload', 'post_upload', 'archive', 'watcher', 'queue', 'state', 'logging'];
        $optionalSections = ['voicemail', 'missed_calls'];
        $unknownSections = array_diff(array_keys($doc['settings']), array_merge($requiredSections, $optionalSections));
        $missingSections = array_diff($requiredSections, array_keys($doc['settings']));
        if ($unknownSections || $missingSections) {
            throw new ConfigProfileError('settings has unknown section(s): ' . implode(', ', $unknownSections) . '; missing section(s): ' . implode(', ', $missingSections));
        }

        $s = $doc['settings'];
        foreach ($s as $name => $section) {
            if (!is_array($section)) {
                throw new ConfigProfileError("settings.{$name} must be an object");
            }
        }
        self::requireKeys($s['general'], ['endpoint', 'api_key', 'auth_header', 'auth_scheme', 'archive_password', 'verify_tls', 'timeout_seconds', 'immediate_retries'], 'settings.general');
        self::requireKeys($s['upload'], ['format'], 'settings.upload');
        self::requireKeys($s['post_upload'], ['on_success', 'move_dir'], 'settings.post_upload');
        self::requireKeys($s['archive'], ['format'], 'settings.archive');
        self::requireKeys($s['watcher'], ['watch_dir', 'filename_pattern', 'min_file_age_seconds', 'exclude_patterns'], 'settings.watcher');
        self::requireKeys($s['queue'], ['max_retries', 'retry_base_seconds', 'retry_max_seconds', 'credit_retry_seconds'], 'settings.queue');
        self::requireKeys($s['state'], ['sweep_interval_seconds', 'stale_processing_seconds', 'retention_days'], 'settings.state');
        self::requireKeys($s['logging'], ['log_level'], 'settings.logging');
        if (!isset($s['missed_calls'])) {
            $s['missed_calls'] = ['enabled' => false, 'poll_interval_seconds' => 30];
        }
        self::requireKeys($s['missed_calls'], ['enabled', 'poll_interval_seconds'], 'settings.missed_calls');
        if (!is_bool($s['missed_calls']['enabled'])) {
            throw new ConfigProfileError('missed_calls.enabled must be a boolean');
        }
        $missedCallsInterval = self::integer($s['missed_calls']['poll_interval_seconds'], 10, 3600, 'missed_calls.poll_interval_seconds');
        if (!isset($s['voicemail'])) {
            $s['voicemail'] = [
                'enabled' => false,
                'spool_dir' => '/var/spool/asterisk/voicemail',
                'folders' => 'INBOX,Old,Urgent,Work,Family,Friends',
                'mailbox_filter' => '',
                'backfill' => false,
                'sweep_interval_seconds' => 60,
                'audio_preference' => 'wav,WAV,gsm',
            ];
        }
        self::requireKeys($s['voicemail'], ['enabled', 'spool_dir', 'folders', 'mailbox_filter', 'backfill', 'sweep_interval_seconds', 'audio_preference'], 'settings.voicemail');

        $endpoint = self::text($s['general']['endpoint'], 'endpoint');
        if (filter_var($endpoint, FILTER_VALIDATE_URL) === false || stripos($endpoint, 'https://') !== 0) {
            throw new ConfigProfileError('endpoint must be a valid HTTPS URL');
        }
        $apiKey = self::text($s['general']['api_key'], 'api_key');
        if (strpos($apiKey, 'sk_live_') !== 0) {
            throw new ConfigProfileError('api_key must start with sk_live_');
        }
        $apiKeyId = self::text($doc['profile']['api_key_id'], 'api_key_id');
        if (!preg_match('/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i', $apiKeyId)) {
            throw new ConfigProfileError('api_key_id must be a UUID');
        }
        $apiKeyPrefix = self::text($doc['profile']['api_key_prefix'], 'api_key_prefix');
        if (strpos($apiKey, $apiKeyPrefix) !== 0) {
            throw new ConfigProfileError('api_key_prefix does not match api_key');
        }
        $authHeader = self::text($s['general']['auth_header'], 'auth_header');
        $authScheme = self::text($s['general']['auth_scheme'], 'auth_scheme', true);
        if (!in_array($authHeader, ['Authorization', 'X-API-Key'], true)
            || ($authHeader === 'Authorization' && $authScheme !== 'Bearer')
            || ($authHeader === 'X-API-Key' && $authScheme !== '')) {
            throw new ConfigProfileError('auth_header and auth_scheme are not supported');
        }
        $transport = self::text($s['upload']['format'], 'upload.format');
        if (!in_array($transport, ['wav', 'gzip', 'zip'], true)) {
            throw new ConfigProfileError('upload.format must be wav, gzip, or zip');
        }
        $password = self::text($s['general']['archive_password'], 'archive_password', true);
        if ($transport !== 'zip' && $password !== '') {
            throw new ConfigProfileError('archive_password is only valid for zip transport');
        }
        if ($password !== '' && (strlen($password) < 12 || strlen($password) > 128)) {
            throw new ConfigProfileError('archive_password must be between 12 and 128 characters');
        }
        if (!is_bool($s['general']['verify_tls'])) {
            throw new ConfigProfileError('verify_tls must be a boolean');
        }
        $onSuccess = self::text($s['post_upload']['on_success'], 'on_success');
        if (!in_array($onSuccess, ['keep', 'move', 'delete'], true)) {
            throw new ConfigProfileError('on_success must be keep, move, or delete');
        }
        $logLevel = strtoupper(self::text($s['logging']['log_level'], 'log_level'));
        if (!in_array($logLevel, ['DEBUG', 'INFO', 'WARNING', 'ERROR'], true)) {
            throw new ConfigProfileError('log_level is invalid');
        }
        if (!is_bool($s['voicemail']['enabled']) || !is_bool($s['voicemail']['backfill'])) {
            throw new ConfigProfileError('voicemail.enabled and voicemail.backfill must be booleans');
        }
        $voicemailFolders = self::text($s['voicemail']['folders'], 'voicemail.folders');
        $voicemailFilter = self::text($s['voicemail']['mailbox_filter'], 'voicemail.mailbox_filter', true);
        $audioPreference = self::text($s['voicemail']['audio_preference'], 'voicemail.audio_preference');
        foreach (explode(',', $audioPreference) as $extension) {
            if (!in_array(trim($extension), ['wav', 'WAV', 'gsm'], true)) {
                throw new ConfigProfileError('voicemail.audio_preference supports wav, WAV, and gsm');
            }
        }
        $pattern = self::text($s['watcher']['filename_pattern'], 'filename_pattern');
        if (@preg_match('#' . str_replace('#', '\\#', $pattern) . '#', '') === false) {
            throw new ConfigProfileError('filename_pattern is not a valid regular expression');
        }
        $excludePattern = self::text($s['watcher']['exclude_patterns'], 'exclude_patterns', true);
        if ($excludePattern !== '' && @preg_match('#' . str_replace('#', '\\#', $excludePattern) . '#', '') === false) {
            throw new ConfigProfileError('exclude_patterns is not a valid regular expression');
        }
        $archiveFormat = strtolower(self::text($s['archive']['format'], 'archive.format'));
        if (!preg_match('/^[a-z0-9]{2,10}$/', $archiveFormat)) {
            throw new ConfigProfileError('archive.format must be a safe file extension');
        }
        $generatedAt = self::text($doc['generated_at'], 'generated_at');
        try {
            new \DateTimeImmutable($generatedAt);
        } catch (\Throwable $exc) {
            throw new ConfigProfileError('generated_at must be an ISO-8601 timestamp');
        }

        return [
            'endpoint' => $endpoint,
            'api_key' => $apiKey,
            'auth_header' => $authHeader,
            'auth_scheme' => $authScheme,
            'archive_password' => $password,
            'verify_tls' => $s['general']['verify_tls'] ? '1' : '0',
            'timeout_seconds' => self::integer($s['general']['timeout_seconds'], 1, 3600, 'timeout_seconds'),
            'immediate_retries' => self::integer($s['general']['immediate_retries'], 0, 10, 'immediate_retries'),
            'upload_format' => $transport,
            'watch_dir' => self::absolutePath($s['watcher']['watch_dir'], 'watch_dir'),
            'filename_pattern' => $pattern,
            'exclude_patterns' => $excludePattern,
            'min_file_age_seconds' => self::integer($s['watcher']['min_file_age_seconds'], 0, 3600, 'min_file_age_seconds'),
            'on_success' => $onSuccess,
            'move_dir' => self::absolutePath($s['post_upload']['move_dir'], 'move_dir'),
            'archive_format' => $archiveFormat,
            'max_retries' => self::integer($s['queue']['max_retries'], 0, 10000, 'max_retries'),
            'retry_base_seconds' => self::integer($s['queue']['retry_base_seconds'], 1, 86400, 'retry_base_seconds'),
            'retry_max_seconds' => self::integer($s['queue']['retry_max_seconds'], 1, 604800, 'retry_max_seconds'),
            'credit_retry_seconds' => self::integer($s['queue']['credit_retry_seconds'], 60, 604800, 'credit_retry_seconds'),
            'sweep_interval_seconds' => self::integer($s['state']['sweep_interval_seconds'], 10, 86400, 'sweep_interval_seconds'),
            'stale_processing_seconds' => self::integer($s['state']['stale_processing_seconds'], 30, 86400, 'stale_processing_seconds'),
            'retention_days' => self::integer($s['state']['retention_days'], 1, 3650, 'retention_days'),
            'missed_calls_enabled' => $s['missed_calls']['enabled'] ? '1' : '0',
            'missed_calls_poll_interval_seconds' => $missedCallsInterval,
            'voicemail_enabled' => $s['voicemail']['enabled'] ? '1' : '0',
            'voicemail_spool_dir' => self::absolutePath($s['voicemail']['spool_dir'], 'voicemail.spool_dir'),
            'voicemail_folders' => $voicemailFolders,
            'voicemail_mailbox_filter' => $voicemailFilter,
            'voicemail_backfill' => $s['voicemail']['backfill'] ? '1' : '0',
            'voicemail_sweep_interval_seconds' => self::integer($s['voicemail']['sweep_interval_seconds'], 10, 86400, 'voicemail.sweep_interval_seconds'),
            'voicemail_audio_preference' => $audioPreference,
            'log_level' => $logLevel,
            '_api_key_id' => $apiKeyId,
            '_api_key_prefix' => $apiKeyPrefix,
            '_generated_at' => $generatedAt,
        ];
    }

    public static function preview(array $settings): array
    {
        $preview = $settings;
        $preview['api_key'] = substr($settings['api_key'], 0, 11) . '...' . substr($settings['api_key'], -4);
        $preview['archive_password'] = $settings['archive_password'] === '' ? '(not set)' : '(configured)';
        return $preview;
    }
}
