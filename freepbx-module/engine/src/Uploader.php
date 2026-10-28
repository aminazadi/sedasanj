<?php
/**
 * Uploader.php - curl multipart upload to the ingest API. Ported from
 * common.py's upload_file() / upload_with_immediate_retries() /
 * _auth_headers() / _content_type_for(). See plan.md §3.7 - wire format,
 * status-code semantics, and backoff math are unchanged from the Python
 * implementation.
 */

namespace Engine;

class UploadError extends \RuntimeException
{
    public ?int $statusCode;
    public bool $retryable;
    public bool $creditBlocked;

    public function __construct(string $message, ?int $statusCode = null, bool $retryable = true, bool $creditBlocked = false)
    {
        parent::__construct($message);
        $this->statusCode = $statusCode;
        $this->retryable = $retryable;
        $this->creditBlocked = $creditBlocked;
    }
}

class Uploader
{
    public static function contentTypeFor(string $filename): string
    {
        $lower = strtolower($filename);
        if (str_ends_with($lower, '.gz')) {
            return 'application/gzip';
        }
        if (str_ends_with($lower, '.zip')) {
            return 'application/zip';
        }
        if (str_ends_with($lower, '.wav')) {
            return 'audio/wav';
        }
        if (str_ends_with($lower, '.gsm')) {
            return 'audio/gsm';
        }
        return 'application/octet-stream';
    }

    private static function authHeaders(array $cfg): array
    {
        $g = $cfg['general'];
        $headers = [];
        if (!empty($g['api_key'])) {
            if (!empty($g['auth_scheme'])) {
                $headers[$g['auth_header']] = trim($g['auth_scheme'] . ' ' . $g['api_key']);
            } else {
                $headers[$g['auth_header']] = $g['api_key'];
            }
        }
        foreach (preg_split('/\R/', $cfg['upload']['extra_headers'] ?? '') as $line) {
            $line = trim($line);
            if ($line === '' || strpos($line, ':') === false) {
                continue;
            }
            [$k, $v] = explode(':', $line, 2);
            $headers[trim($k)] = trim($v);
        }
        return $headers;
    }

    /**
     * @throws UploadError
     */
    public static function uploadFile(array $cfg, string $filepath, array $metadata, ?\Closure $log = null): array
    {
        $log = $log ?? function (string $msg) {};
        $g = $cfg['general'];
        $u = $cfg['upload'];
        $headers = self::authHeaders($cfg);

        $formMetadata = IngestMapper::toIngestForm($metadata);

        $missing = [];
        $requiredFields = !empty($metadata['_voicemail'])
            ? ['asterisk_uniqueid', 'mailbox', 'context', 'folder', 'started_at']
            : Config::REQUIRED_INGEST_FIELDS;
        foreach ($requiredFields as $field) {
            if (empty($formMetadata[$field])) {
                $missing[] = $field;
            }
        }
        if ($missing) {
            $gotKeys = implode(', ', array_keys($formMetadata));
            throw new UploadError(
                'Missing required ingest field(s): ' . implode(', ', $missing) . " (got keys: {$gotKeys})",
                null,
                false
            );
        }

        $idem = $metadata['uniqueid'] ?? $metadata['asterisk_uniqueid'] ?? null;
        if ($idem) {
            $headers['Idempotency-Key'] = $headers['Idempotency-Key'] ?? (string) $idem;
        }

        if (!empty($g['archive_password'])) {
            $headers['X-CBI-Archive-Password'] = $g['archive_password'];
        }

        if (!is_file($filepath)) {
            throw new UploadError("Recording file not found: {$filepath}", null, false);
        }

        $filename = basename($filepath);
        $contentType = self::contentTypeFor($filename);

        $postFields = [];
        unset($formMetadata['_state_key'], $formMetadata['_voicemail'], $formMetadata['_vm_source_dir']);
        if (($u['metadata_mode'] ?? 'form_fields') === 'json_field') {
            $postFields[$u['metadata_json_field_name']] = json_encode($formMetadata);
        } else {
            foreach ($formMetadata as $k => $v) {
                $postFields[$k] = (string) $v;
            }
        }
        $postFields[$u['file_field_name']] = new \CURLFile($filepath, $contentType, $filename);

        $ch = curl_init();
        $headerLines = [];
        foreach ($headers as $k => $v) {
            $headerLines[] = "{$k}: {$v}";
        }

        curl_setopt_array($ch, [
            CURLOPT_URL => !empty($metadata['_voicemail'])
                ? preg_replace('#/calls/?$#', '/voicemails', $g['endpoint'])
                : $g['endpoint'],
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $postFields,
            CURLOPT_HTTPHEADER => $headerLines,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => (int) $g['timeout_seconds'],
            CURLOPT_SSL_VERIFYPEER => (bool) $g['verify_tls'],
            CURLOPT_SSL_VERIFYHOST => $g['verify_tls'] ? 2 : 0,
        ]);

        $body = curl_exec($ch);
        if ($body === false) {
            $err = curl_error($ch);
            curl_close($ch);
            throw new UploadError("Network error uploading {$filepath}: {$err}", null, true);
        }
        $statusCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($statusCode >= 200 && $statusCode < 300) {
            $log("Uploaded {$filepath} -> {$g['endpoint']} [{$statusCode}]");
            return ['status_code' => $statusCode, 'body' => $body];
        }

        // Ingest API status code semantics:
        //   400 invalid metadata / malformed request       -> non-retryable
        //   401 missing/invalid/revoked API key            -> non-retryable
        //   402 insufficient processing credit              -> credit-blocked retry
        //   413 compressed or extracted file too large      -> non-retryable
        //   415 unsupported archive / invalid WAV media     -> non-retryable
        //   422 archive format/unsafe archive/ZIP password  -> non-retryable
        //   429 rate limit exceeded                          -> retryable
        //   5xx server side                                  -> retryable
        $decoded = json_decode((string) $body, true);
        $declaredRetryable = is_array($decoded)
            && isset($decoded['error']) && is_array($decoded['error'])
            && array_key_exists('retryable', $decoded['error'])
            ? (bool) $decoded['error']['retryable']
            : null;
        $retryable = $declaredRetryable !== null
            ? $declaredRetryable
            : ($statusCode === 402 || $statusCode === 429 || $statusCode >= 500);
        $snippet = substr((string) $body, 0, 500);
        foreach (array_filter([
            $g['api_key'] ?? '',
            $g['archive_password'] ?? '',
        ]) as $secret) {
            $snippet = str_replace((string) $secret, '[REDACTED]', $snippet);
        }
        $snippet = preg_replace('/sk_live_[A-Za-z0-9_\-]+/', '[REDACTED]', $snippet);
        throw new UploadError("Endpoint returned {$statusCode}: {$snippet}", $statusCode, $retryable, $statusCode === 402);
    }

    public static function uploadMissedCall(array $cfg, array $event, ?\Closure $log = null): array
    {
        $log = $log ?? function (string $msg) {};
        $endpoint = preg_replace('#/calls/?$#', '/missed-calls', $cfg['general']['endpoint']);
        $headers = self::authHeaders($cfg);
        $headers['Content-Type'] = 'application/json';
        $headers['Idempotency-Key'] = (string) $event['asterisk_uniqueid'];
        $body = json_encode($event, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($body === false) {
            throw new UploadError('Could not encode missed-call event', null, false);
        }
        $headerLines = [];
        foreach ($headers as $key => $value) {
            $headerLines[] = $key . ': ' . $value;
        }
        $ch = curl_init();
        curl_setopt_array($ch, [
            CURLOPT_URL => $endpoint,
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_HTTPHEADER => $headerLines,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => (int) $cfg['general']['timeout_seconds'],
            CURLOPT_SSL_VERIFYPEER => (bool) $cfg['general']['verify_tls'],
            CURLOPT_SSL_VERIFYHOST => $cfg['general']['verify_tls'] ? 2 : 0,
        ]);
        $response = curl_exec($ch);
        if ($response === false) {
            $error = curl_error($ch);
            curl_close($ch);
            throw new UploadError('Network error uploading missed call: ' . $error, null, true);
        }
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        $decoded = json_decode((string) $response, true);
        if ($status >= 200 && $status < 300) {
            $log('Uploaded missed call ' . $event['asterisk_uniqueid'] . ' [' . $status . ']');
            return ['status_code' => $status, 'body' => $response, 'replayed' => !empty($decoded['replayed'])];
        }
        $declared = is_array($decoded) && isset($decoded['error']) && is_array($decoded['error'])
            && array_key_exists('retryable', $decoded['error']) ? (bool) $decoded['error']['retryable'] : null;
        $retryable = $declared !== null ? $declared : ($status === 402 || $status === 429 || $status >= 500);
        $snippet = substr((string) $response, 0, 500);
        $snippet = str_replace((string) ($cfg['general']['api_key'] ?? ''), '[REDACTED]', $snippet);
        throw new UploadError('Missed-call endpoint returned ' . $status . ': ' . $snippet, $status, $retryable, $status === 402);
    }

    public static function uploadWithImmediateRetries(array $cfg, string $filepath, array $metadata, ?\Closure $log = null): array
    {
        $log = $log ?? function (string $msg) {};
        $attempts = max(1, (int) $cfg['general']['immediate_retries'] + 1);
        $lastExc = null;
        for ($i = 0; $i < $attempts; $i++) {
            try {
                return self::uploadFile($cfg, $filepath, $metadata, $log);
            } catch (UploadError $exc) {
                $lastExc = $exc;
                $log(sprintf('Upload attempt %d/%d failed: %s', $i + 1, $attempts, $exc->getMessage()));
                if (!$exc->retryable || $exc->creditBlocked) {
                    break;
                }
                if ($i < $attempts - 1) {
                    usleep((int) min(2 ** $i, 10) * 1000000);
                }
            }
        }
        throw $lastExc;
    }
}
