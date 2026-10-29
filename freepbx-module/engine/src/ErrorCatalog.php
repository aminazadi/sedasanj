<?php
/**
 * ErrorCatalog.php - stable error codes (SS-<AREA>-<NNNN>) for the Seda Sanj
 * module. Every failure the module can report carries one of these codes so a
 * log line, the admin page and the help center (https://sedasanj.ir/help/errors/<CODE>)
 * all talk about the same thing. Never reuse or renumber a code; add new ones.
 *
 * Areas: CFG config, SVC service, HOOK recording hook, AUD audio, STG staging
 * and archive, UPL upload and network, QUE queue, SWP sweeper, VMX voicemail,
 * MCP missed calls, CDR call records, SYS system, UPD updates, DEP dependencies,
 * EXT extension sync.
 * HTTP-status codes use SS-UPL-0<status> (e.g. SS-UPL-0401).
 */

namespace Engine;

class ErrorCatalog
{
    const HELP_BASE_URL = 'https://sedasanj.ir/help/errors/';

    /** code => [severity, retryable, title, suggested action] */
    const ENTRIES = [
        // Configuration
        'SS-CFG-1001' => ['error', false, 'Configuration file not found', 'Save the settings from Admin > Seda Sanj, or reinstall the module.'],
        'SS-CFG-1002' => ['error', false, 'Configuration file cannot be parsed', 'Re-save the settings from the module page or restore config.ini.example.'],
        'SS-CFG-1003' => ['error', false, 'Configuration value is invalid', 'Open the module page, correct the highlighted setting and save again.'],
        'SS-CFG-1004' => ['error', false, 'Upload endpoint is missing or not https', 'Enter the https:// upload endpoint shown in your Seda Sanj panel.'],
        // Service
        'SS-SVC-1001' => ['error', false, 'Service cannot start: configuration error', 'Fix the configuration (see the preceding SS-CFG error) and restart the service.'],
        'SS-SVC-1002' => ['warning', true, 'Persistent storage fell back to JSON files', 'Check that pdo_sqlite is loaded and that /var/lib/asterisk-recording-uploader is owned by asterisk.'],
        'SS-SVC-1003' => ['error', true, 'Unexpected error in a service loop', 'Read the message; if it repeats, run the doctor command and send the support bundle.'],
        'SS-SVC-1004' => ['warning', false, 'pcntl extension is missing', 'Install php-pcntl for a clean service stop, or accept a forced stop by systemd.'],
        'SS-SVC-1005' => ['error', false, 'Another service instance is already running', 'Stop the duplicate: systemctl status asterisk-recording-uploader; only one instance may run.'],
        // Recording hook
        'SS-HOOK-1001' => ['error', false, 'Recording hook was called without required arguments', 'Re-run the module activation so the MixMonitor globals are rewritten.'],
        'SS-HOOK-1002' => ['error', false, 'Recording hook rejected an unsafe argument', 'Normally harmless (a caller ID with unusual characters). If it affects normal calls, check the MIXMON_POST globals.'],
        'SS-HOOK-1003' => ['error', true, 'Stereo merge of the call legs failed', 'Check that MON_FMT is wav and that disk space is available; the recording is kept and retried.'],
        'SS-HOOK-1004' => ['error', true, 'Metadata sidecar could not be written', 'Free disk space or fix ownership of the monitor directory.'],
        'SS-HOOK-1005' => ['critical', false, 'FreePBX callrecording patch is missing (updated by FreePBX?)', 'Re-apply the module activation; recordings are not passing through the hook until you do.'],
        // Audio
        'SS-AUD-1001' => ['error', false, 'Audio file cannot be read', 'Check that the file exists and is readable by the asterisk user.'],
        'SS-AUD-1002' => ['error', false, 'Audio file is not a valid or complete WAV', 'The recording was cut off; nothing to fix unless it happens on every call.'],
        'SS-AUD-1003' => ['error', false, 'Audio format is not supported (needs 16-bit PCM WAV)', 'Set the FreePBX recording format to WAV.'],
        'SS-AUD-1004' => ['error', true, 'Call legs do not match (rate or bit depth)', 'Use one codec for both legs of the recording.'],
        'SS-AUD-1005' => ['warning', false, 'Recording has no audio samples', 'The call was never bridged; the file is ignored.'],
        // Staging and archive
        'SS-STG-1001' => ['error', true, 'Recording could not be staged (copy or gzip failed)', 'Free disk space and check ownership of /var/spool/asterisk-recording-uploader.'],
        'SS-STG-1002' => ['warning', false, 'ffmpeg failed while creating the local archive copy', 'Install ffmpeg or set the archive format to wav or gsm. Upload is not blocked.'],
        'SS-STG-1003' => ['warning', false, 'No GSM encoder is available for the local archive copy', 'Install gsm-utils, use the bundled encoder for your CPU, or set the archive format to wav. Upload is not blocked.'],
        'SS-STG-1004' => ['error', true, 'ZIP encryption (7zip) failed', 'Check that the bundled 7zzs binary is executable and not on a noexec mount, or use gzip uploads.'],
        'SS-STG-1005' => ['error', false, 'Staged file is larger than the API limit', 'Shorten the recording or raise the limit on the server side.'],
        'SS-STG-1006' => ['warning', false, 'GSM archive needs an 8 kHz source', 'Set archive format to wav for wideband recordings. Upload is not blocked.'],
        'SS-STG-1007' => ['error', true, 'Metadata sidecar for the staged file could not be written', 'Free disk space or fix ownership of the spool directory.'],
        'SS-STG-1008' => ['error', true, 'Voicemail audio could not be converted', 'Install ffmpeg or use the bundled binary; check the voicemail file.'],
        // Upload and network
        'SS-UPL-1001' => ['error', false, 'Required call metadata is missing', 'Usually an unusual call (no caller or dialed number). The recording is kept in failed/.'],
        'SS-UPL-1002' => ['error', false, 'Recording file disappeared before upload', 'Check for a second uploader instance or manual deletion.'],
        'SS-UPL-1003' => ['info', false, 'Server reported this call as already received', 'No action; if the call is missing in the panel contact support with the call ID.'],
        'SS-UPL-2001' => ['error', true, 'Network error while uploading', 'Check connectivity from the PBX to the endpoint (curl -v).'],
        'SS-UPL-2002' => ['error', true, 'DNS lookup of the endpoint failed', 'Fix the PBX DNS resolver or the endpoint host name.'],
        'SS-UPL-2003' => ['error', true, 'Connection to the endpoint was refused or unreachable', 'Check firewall rules and the endpoint URL and port.'],
        'SS-UPL-2004' => ['error', true, 'Upload timed out', 'Check the uplink speed; raise the timeout for long recordings.'],
        'SS-UPL-2005' => ['error', true, 'TLS/certificate problem talking to the endpoint', 'Fix the PBX clock and install current ca-certificates; do not disable verification in production.'],
        'SS-UPL-0400' => ['error', false, 'Endpoint rejected the request (HTTP 400)', 'Check the endpoint URL and the upload format setting.'],
        'SS-UPL-0401' => ['error', false, 'API key rejected (HTTP 401)', 'Create/rotate the key in the panel and re-import the configuration. Queued recordings are kept and resume automatically.'],
        'SS-UPL-0402' => ['warning', true, 'Credit exhausted (HTTP 402)', 'Top up the account; uploads resume automatically.'],
        'SS-UPL-0403' => ['error', false, 'Access denied or account suspended (HTTP 403)', 'Contact support; queued recordings are kept and resume automatically.'],
        'SS-UPL-0404' => ['error', false, 'Endpoint path not found (HTTP 404)', 'The endpoint must end with /v1/ingest/calls.'],
        'SS-UPL-0413' => ['error', false, 'Upload too large (HTTP 413)', 'Raise the proxy body limit or shorten recordings.'],
        'SS-UPL-0415' => ['error', false, 'Upload format does not match the API key (HTTP 415)', 'Set the upload format (gzip/zip) to the one configured for the key.'],
        'SS-UPL-0422' => ['error', false, 'Server rejected the data (HTTP 422)', 'Check the archive password and the call numbers; see the message for the field.'],
        'SS-UPL-0429' => ['warning', true, 'Rate limited (HTTP 429)', 'No action; the module backs off automatically.'],
        'SS-UPL-0500' => ['error', true, 'Server error (HTTP 5xx)', 'No action; the module retries. If it persists, check the Seda Sanj status page.'],
        'SS-UPL-0599' => ['error', false, 'Unexpected HTTP response', 'Read the status and message; check proxies in front of the endpoint.'],
        // Queue
        'SS-QUE-1001' => ['warning', false, 'Queued recording no longer exists', 'Usually raced with a manual cleanup; no action.'],
        'SS-QUE-1002' => ['error', true, 'Retry queue could not be written', 'Free disk space and fix ownership of /var/lib/asterisk-recording-uploader.'],
        'SS-QUE-1003' => ['warning', true, 'Upload attempt failed; will retry', 'No action unless it keeps failing; see the attached cause code.'],
        'SS-QUE-1004' => ['error', false, 'Upload failed permanently; recording moved to failed/', 'Fix the cause, then run requeue-failed to retry.'],
        'SS-QUE-1005' => ['warning', true, 'Uploads are paused: credit exhausted', 'Top up the account; the queue resumes automatically.'],
        'SS-QUE-1006' => ['warning', true, 'Uploads are paused: configuration or account problem', 'Fix the API key / account (see the attached cause code); the queue resumes automatically.'],
        // Sweeper
        'SS-SWP-1001' => ['warning', false, 'Orphan recording kept: metadata is incomplete', 'Inspect the file; delete or re-queue it manually.'],
        'SS-SWP-1002' => ['info', false, 'Orphan recording recovered and queued', 'No action.'],
        // Voicemail
        'SS-VMX-1001' => ['error', false, 'Voicemail spool is missing or unreadable', 'Fix the spool path or give the asterisk user read access.'],
        'SS-VMX-1002' => ['warning', true, 'Voicemail metadata is incomplete', 'Usually transient while Asterisk is still writing the message.'],
        'SS-VMX-1003' => ['error', true, 'Voicemail processing failed', 'See the attached cause code.'],
        // Missed calls and CDR
        'SS-MCP-1001' => ['error', true, 'Missed-call poll failed: CDR unavailable', 'Check MariaDB access and cdr.conf (unanswered=yes).'],
        'SS-MCP-1002' => ['error', true, 'Missed-call upload failed', 'See the attached cause code.'],
        'SS-MCP-1003' => ['error', true, 'Missed-call state could not be saved', 'Free disk space and fix ownership of the state directory.'],
        'SS-CDR-1001' => ['error', false, 'FreePBX bootstrap (/etc/freepbx.conf) not found', 'Missed calls and answered-extension lookup need a FreePBX host.'],
        'SS-CDR-1002' => ['error', false, 'CDR table is missing required columns', 'Check the CDR database schema.'],
        'SS-CDR-1003' => ['error', true, 'CDR database connection failed', 'Check that MariaDB is running and FreePBX can reach it.'],
        // System
        'SS-SYS-1001' => ['error', false, 'PHP version is too old', 'Install PHP 7.4 or newer for the CLI engine.'],
        'SS-SYS-1002' => ['error', false, 'A required PHP extension is missing', 'Install the extension named in the message and restart PHP/the service.'],
        'SS-SYS-1003' => ['error', false, 'FreePBX version is not supported', 'Supported: FreePBX 15 (PHP 7.4 CLI), 16 and 17.'],
        'SS-SYS-1004' => ['warning', false, 'Root activation is required', 'Run the activation command shown on the module page as root.'],
        'SS-SYS-1005' => ['error', true, 'Disk is full or nearly full', 'Free space on the volume holding /var/spool and /var/lib.'],
        'SS-SYS-1006' => ['warning', false, 'System clock differs from the server', 'Fix NTP on the PBX; skew breaks TLS and scheduling.'],
        'SS-SYS-1007' => ['error', false, 'A required directory is not writable', 'Fix ownership: chown -R asterisk:asterisk on the module directories.'],
        // Updates
        // Extension sync
        'SS-EXT-1001' => ['error', false, 'FreePBX extension list is unavailable', 'Run the sync from a FreePBX host with the core module enabled (needs /etc/freepbx.conf).'],
        'SS-EXT-1002' => ['warning', false, 'FreePBX has no extensions to sync', 'Create extensions in Applications > Extensions, then sync again.'],
        'SS-EXT-1003' => ['error', true, 'Extension sync could not reach Seda Sanj', 'Check the endpoint, API key and connectivity on the module page, then sync again.'],
        // Updates
        'SS-UPD-1001' => ['warning', false, 'Automatic update is unavailable on this host', 'See the reason shown on the module page (sodium, helper, signing key).'],
        'SS-UPD-1002' => ['error', false, 'Release signature or checksum is invalid', 'Do not install; contact support.'],
        'SS-UPD-1003' => ['error', true, 'Release download failed', 'Check connectivity and disk space, then retry.'],
        'SS-UPD-1004' => ['error', false, 'Downgrade or replay of an older release refused', 'No action; only newer releases are installed automatically.'],
        'SS-UPD-1005' => ['error', false, 'Update helper failed', 'Open the update log on the module page; the previous version is restored automatically.'],
        'SS-UPD-1006' => ['critical', false, 'Update failed and rollback was incomplete', 'Restore from the backup path shown in the update log.'],
        // Dependencies
        'SS-DEP-1001' => ['error', false, 'A required FreePBX module is not installed', 'Install it from the Dependencies tab or with fwconsole ma downloadinstall.'],
        'SS-DEP-1002' => ['error', false, 'A required PHP extension is missing', 'Install the extension from your OS packages.'],
        'SS-DEP-1003' => ['warning', false, 'An optional tool is missing', 'Install it only if you use the related feature.'],
    ];

    public static function exists(string $code): bool
    {
        return isset(self::ENTRIES[$code]);
    }

    /** @return array{code:string,severity:string,retryable:bool,title:string,action:string,help_url:string}|null */
    public static function lookup(string $code): ?array
    {
        if (!isset(self::ENTRIES[$code])) {
            return null;
        }
        [$severity, $retryable, $title, $action] = self::ENTRIES[$code];
        return [
            'code' => $code,
            'severity' => $severity,
            'retryable' => $retryable,
            'title' => $title,
            'action' => $action,
            'help_url' => self::helpUrl($code),
        ];
    }

    public static function helpUrl(string $code): string
    {
        return self::HELP_BASE_URL . rawurlencode($code);
    }

    /** Maps an HTTP status from the ingest API to its catalog code. */
    public static function forHttpStatus(int $status): string
    {
        $known = [400, 401, 402, 403, 404, 413, 415, 422, 429];
        if (in_array($status, $known, true)) {
            return sprintf('SS-UPL-0%d', $status);
        }
        if ($status >= 500) {
            return 'SS-UPL-0500';
        }
        return 'SS-UPL-0599';
    }

    /** Maps a curl errno to a network code. */
    public static function forCurlErrno(int $errno): string
    {
        switch ($errno) {
            case 6:
                return 'SS-UPL-2002';
            case 7:
                return 'SS-UPL-2003';
            case 28:
                return 'SS-UPL-2004';
            case 35:
            case 51:
            case 58:
            case 59:
            case 60:
            case 77:
            case 83:
                return 'SS-UPL-2005';
            default:
                return 'SS-UPL-2001';
        }
    }

    /** Appends " [code] help-url" to a message so GUI text and logs link to the help center. */
    public static function describe(string $code, string $message): string
    {
        return $message . ' [' . $code . ']';
    }
}
