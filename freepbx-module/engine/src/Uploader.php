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
    /** Account/endpoint/key problem: keep the recording and pause until the admin fixes it. */
    public bool $configBlocked;
    public string $errorCode;
    /** @var array<string,mixed> structured details for the log (never secrets) */
    public array $context;

    public function __construct(
        string $message,
        ?int $statusCode = null,
        bool $retryable = true,
        bool $creditBlocked = false,
        string $errorCode = 'SS-UPL-2001',
        array $context = [],
        bool $configBlocked = false
    ) {
        parent::__construct($message);
        $this->statusCode = $statusCode;
        $this->retryable = $retryable || $configBlocked;
        $this->creditBlocked = $creditBlocked;
        $this->configBlocked = $configBlocked;
        $this->errorCode = $errorCode;
        $this->context = $context;
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

    /** Server error.code values that mean "the key/account/format is wrong", not "this file is bad". */
    const CONFIG_BLOCKING_CODES = [
        'unauthorized', 'forbidden', 'tenant_suspended', 'unsupported_archive',
        'archive_password_required', 'archive_password_invalid',
    ];
    /** Server error.code values that are about this one recording and will never succeed on retry. */
    const DATA_ERROR_CODES = [
        'invalid_request', 'unsupported_audio', 'archive_too_large', 'archive_unsafe',
    ];

    private static function userAgent(): string
    {
        $version = 'unknown';
        $xml = dirname(__DIR__, 2) . '/module.xml';
        if (is_file($xml) && preg_match('#<version>([^<]+)</version>#', (string) @file_get_contents($xml), $m)) {
            $version = $m[1];
        }
        return 'SedaSanj-FreePBX/' . $version . ' PHP/' . PHP_VERSION;
    }

    /** voicemail/missed-call endpoints are siblings of .../calls; refuse to guess otherwise. */
    private static function siblingEndpoint(string $endpoint, string $leaf): string
    {
        $url = preg_replace('#/calls/?$#', '/' . $leaf, $endpoint, -1, $count);
        if ($url === null || $count !== 1) {
            throw new UploadError(
                "The upload endpoint must end with /calls to derive the {$leaf} endpoint",
                null,
                false,
                false,
                'SS-CFG-1004'
            );
        }
        return $url;
    }

    /** Upload time budget: configured timeout, extended for large files so slow uplinks can finish. */
    private static function timeoutFor(array $cfg, string $filepath): int
    {
        $configured = max(1, (int) $cfg['general']['timeout_seconds']);
        $size = is_file($filepath) ? (int) @filesize($filepath) : 0;
        return (int) min(3600, max($configured, 30 + intdiv($size, 32768)));
    }

    /**
     * Sends a prepared request and returns [status, body, headers, info]; throws a coded
     * UploadError for transport failures (DNS, refused, timeout, TLS...).
     *
     * @return array{0:int,1:string,2:array<string,string>,3:array<string,mixed>}
     */
    private static function send(array $cfg, string $url, array $options, array $headerLines, string $what): array
    {
        $g = $cfg['general'];
        $requestId = 'ss-' . bin2hex(random_bytes(8));
        $headerLines[] = 'User-Agent: ' . self::userAgent();
        $headerLines[] = 'X-Request-ID: ' . $requestId;
        $responseHeaders = [];
        $ch = curl_init();
        // CURLOPT_POSTFIELDS (in $options) implies POST. Setting CURLOPT_POST afterwards would reset
        // a multipart body to an empty urlencoded one, so it must not be listed here.
        curl_setopt_array($ch, $options + [
            CURLOPT_URL => $url,
            CURLOPT_HTTPHEADER => $headerLines,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_SSL_VERIFYPEER => (bool) $g['verify_tls'],
            CURLOPT_SSL_VERIFYHOST => $g['verify_tls'] ? 2 : 0,
            CURLOPT_HEADERFUNCTION => function ($handle, string $line) use (&$responseHeaders): int {
                $parts = explode(':', $line, 2);
                if (count($parts) === 2) {
                    $responseHeaders[strtolower(trim($parts[0]))] = trim($parts[1]);
                }
                return strlen($line);
            },
        ]);
        $body = curl_exec($ch);
        $info = [
            'request_id' => $requestId,
            'total_ms' => (int) round(((float) curl_getinfo($ch, CURLINFO_TOTAL_TIME)) * 1000),
            'dns_ms' => (int) round(((float) curl_getinfo($ch, CURLINFO_NAMELOOKUP_TIME)) * 1000),
            'connect_ms' => (int) round(((float) curl_getinfo($ch, CURLINFO_CONNECT_TIME)) * 1000),
            'bytes' => (int) curl_getinfo($ch, CURLINFO_SIZE_UPLOAD),
        ];
        if ($body === false) {
            $errno = curl_errno($ch);
            $err = Logger::redact(curl_error($ch), array_filter([$g['api_key'] ?? '', $g['archive_password'] ?? '']));
            curl_close($ch);
            $code = ErrorCatalog::forCurlErrno($errno);
            throw new UploadError(
                "Network error uploading {$what}: {$err}",
                null,
                true,
                false,
                $code,
                $info + ['curl_errno' => $errno]
            );
        }
        $status = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if (isset($responseHeaders['x-request-id'])) {
            $info['server_request_id'] = $responseHeaders['x-request-id'];
        }
        if (isset($responseHeaders['retry-after']) && ctype_digit($responseHeaders['retry-after'])) {
            $info['retry_after'] = min(3600, (int) $responseHeaders['retry-after']);
        }
        return [$status, (string) $body, $responseHeaders, $info];
    }

    /**
     * Turns a non-2xx response into a coded UploadError and decides how the queue treats it:
     *  - credit (402): keep, retry on the credit schedule, do not consume attempts;
     *  - config-blocking (401/403/404/405 or a server code like unauthorized/tenant_suspended/
     *    archive_password_*): keep everything and pause - the admin must fix the key/account;
     *  - data errors (invalid_request, unsupported_audio, 413, 415, 422): this file will never
     *    succeed, move it to failed/;
     *  - everything else (429, 5xx, proxy 4xx without a recognised server code): retry.
     */
    private static function classifyHttpFailure(array $cfg, int $status, string $body, array $info, string $what): UploadError
    {
        $decoded = json_decode($body, true);
        $serverCode = is_array($decoded) && isset($decoded['error']['code']) && is_string($decoded['error']['code'])
            ? $decoded['error']['code'] : '';
        $declared = is_array($decoded) && isset($decoded['error']) && is_array($decoded['error'])
            && array_key_exists('retryable', $decoded['error']) ? (bool) $decoded['error']['retryable'] : null;
        if (is_array($decoded) && isset($decoded['error']['request_id']) && is_string($decoded['error']['request_id'])) {
            $info['server_request_id'] = $decoded['error']['request_id'];
        }

        $configBlocked = in_array($serverCode, self::CONFIG_BLOCKING_CODES, true)
            || ($serverCode === '' && in_array($status, [401, 403, 404, 405], true));
        if ($configBlocked) {
            $retryable = true;
        } elseif ($declared !== null) {
            $retryable = $declared;
        } elseif (in_array($serverCode, self::DATA_ERROR_CODES, true) || in_array($status, [400, 413, 415, 422], true)) {
            $retryable = false;
        } else {
            $retryable = true; // 402, 408, 429, 5xx and unrecognised proxy responses
        }

        $secrets = array_filter([$cfg['general']['api_key'] ?? '', $cfg['general']['archive_password'] ?? '']);
        $snippet = Logger::redact(substr($body, 0, 500), $secrets);
        $info += ['http_status' => $status, 'server_code' => $serverCode];
        return new UploadError(
            "{$what} returned {$status}: {$snippet}",
            $status,
            $retryable,
            $status === 402,
            ErrorCatalog::forHttpStatus($status),
            $info,
            $configBlocked
        );
    }

    /**
     * @throws UploadError
     * @return array{status_code:int,body:string,replayed:bool,request_id:string,info:array<string,mixed>}
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
                false,
                false,
                'SS-UPL-1001',
                ['missing' => implode(',', $missing)]
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
            throw new UploadError("Recording file not found: {$filepath}", null, false, false, 'SS-UPL-1002');
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

        $headerLines = [];
        foreach ($headers as $k => $v) {
            $headerLines[] = "{$k}: {$v}";
        }
        $url = !empty($metadata['_voicemail']) ? self::siblingEndpoint($g['endpoint'], 'voicemails') : $g['endpoint'];

        [$statusCode, $body, , $info] = self::send($cfg, $url, [
            CURLOPT_POSTFIELDS => $postFields,
            CURLOPT_TIMEOUT => self::timeoutFor($cfg, $filepath),
        ], $headerLines, $filename);

        if ($statusCode >= 200 && $statusCode < 300) {
            $decoded = json_decode($body, true);
            $replayed = is_array($decoded) && !empty($decoded['replayed']);
            $log("Uploaded {$filepath} -> {$g['endpoint']} [{$statusCode}]" . ($replayed ? ' (server reports it was already received) [SS-UPL-1003]' : ''));
            return ['status_code' => $statusCode, 'body' => $body, 'replayed' => $replayed,
                'request_id' => $info['request_id'], 'info' => $info];
        }

        throw self::classifyHttpFailure($cfg, $statusCode, $body, $info, 'Endpoint');
    }

    /**
     * POSTs a small JSON document to a sibling of the calls endpoint (for example "module/diagnostics").
     *
     * @throws UploadError
     * @return array{status_code:int,body:string}
     */
    public static function postJson(array $cfg, string $leaf, array $payload): array
    {
        $endpoint = self::siblingEndpoint($cfg['general']['endpoint'], $leaf);
        $headers = self::authHeaders($cfg);
        $headers['Content-Type'] = 'application/json';
        $body = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE);
        $headerLines = [];
        foreach ($headers as $key => $value) {
            $headerLines[] = $key . ': ' . $value;
        }
        [$status, $response, , $info] = self::send($cfg, $endpoint, [
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_TIMEOUT => 20,
        ], $headerLines, $leaf);
        if ($status >= 200 && $status < 300) {
            return ['status_code' => $status, 'body' => $response];
        }
        throw self::classifyHttpFailure($cfg, $status, $response, $info, $leaf);
    }

    public static function uploadMissedCall(array $cfg, array $event, ?\Closure $log = null): array
    {
        $log = $log ?? function (string $msg) {};
        $endpoint = self::siblingEndpoint($cfg['general']['endpoint'], 'missed-calls');
        $headers = self::authHeaders($cfg);
        $headers['Content-Type'] = 'application/json';
        $headers['Idempotency-Key'] = (string) $event['asterisk_uniqueid'];
        $body = json_encode($event, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        if ($body === false) {
            throw new UploadError('Could not encode missed-call event', null, false, false, 'SS-UPL-1001');
        }
        $headerLines = [];
        foreach ($headers as $key => $value) {
            $headerLines[] = $key . ': ' . $value;
        }
        [$status, $response, , $info] = self::send($cfg, $endpoint, [
            CURLOPT_POSTFIELDS => $body,
            CURLOPT_TIMEOUT => max(1, (int) $cfg['general']['timeout_seconds']),
        ], $headerLines, 'missed call');
        $decoded = json_decode($response, true);
        if ($status >= 200 && $status < 300) {
            $log('Uploaded missed call ' . $event['asterisk_uniqueid'] . ' [' . $status . ']');
            return ['status_code' => $status, 'body' => $response, 'replayed' => !empty($decoded['replayed']),
                'request_id' => $info['request_id'], 'info' => $info];
        }
        throw self::classifyHttpFailure($cfg, $status, $response, $info, 'Missed-call endpoint');
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
                $log(sprintf('Upload attempt %d/%d failed: %s [%s]', $i + 1, $attempts, $exc->getMessage(), $exc->errorCode));
                if (!$exc->retryable || $exc->creditBlocked || $exc->configBlocked) {
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
