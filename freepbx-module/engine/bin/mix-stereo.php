#!/usr/bin/env php
<?php
/**
 * bin/mix-stereo.php - MIXMON_POST post-processing hook, replacing
 * scripts/mix-stereo.sh. Same positional-argument contract as the bash
 * version (see dialplan/globals-custom-mixmon.conf):
 *
 *   $1  recording directory (with trailing slash)
 *   $2  ${CALLFILENAME}
 *   $3  Asterisk ${UNIQUEID}     (epoch.sequence)
 *   $4  ${CALLERID(num)}
 *   $5  ${CDR(dnid)}
 *   $6  ${CDR(duration)}         usually EMPTY here - see note below.
 *   $7  ${CDR(dst)}              fallback destination.
 *   $8  ${FROM_DID}              preferred inbound DID.
 *
 * Steps:
 *   1. Merge MixMonitor's per-leg recv_/trans_ files into one stereo WAV
 *      (stereo_<name>.wav) in-process via Engine\Audio\Wav::mergeStereo()
 *      (replaces `sox -M`), then delete the legs and the raw file.
 *   2. Read the merged file's own duration directly from its data chunk
 *      (replaces `soxi -D` / `ffprobe`) - this is exact, and doesn't
 *      depend on ${CDR(duration)}, which is not yet finalized at hangup
 *      and is usually empty when this script runs.
 *   3. Hand off to uploader.php (same process model as before: this
 *      script does the audio work, uploader.php does staging/upload).
 */

require __DIR__ . '/../autoload.php';

use Engine\Audio\Wav;
use Engine\Audio\WavError;
use Engine\AnsweredExtension;

/**
 * Logs a coded message to the module log (when the config can be loaded) and always to STDERR,
 * which is the only channel that reaches Asterisk's console. Never throws.
 */
function mixstereo_say(string $code, string $message, array $ctx = []): void
{
    fwrite(STDERR, "mix-stereo.php: {$message} [{$code}]\n");
    try {
        static $log = false;
        if ($log === false) {
            $log = new Engine\Logger(Engine\Config::load(getenv('ARU_CONFIG') ?: null), 'aru.hook');
        }
        $log->coded($code, $message, $ctx);
    } catch (\Throwable $exc) {
        // no readable config yet: STDERR above is all we have
    }
}

function mixstereo_main(array $argv): int
{
    // Long calls are merged in memory (two legs + the interleaved result).
    @ini_set('memory_limit', '768M');
    $dir = $argv[1] ?? '';
    $name = $argv[2] ?? '';
    $uniqueId = $argv[3] ?? '';
    $caller = $argv[4] ?? '';
    $dialed = $argv[5] ?? '';
    $cdrDuration = $argv[6] ?? '';
    $cdrDestination = $argv[7] ?? '';
    $fromDid = $argv[8] ?? '';
    // Defence in depth behind the dialplan FILTER(): never trust an argument
    // that still carries shell metacharacters or path tricks.
    $safe = '/^[0-9A-Za-z*#+_.\-]*$/';
    foreach (['name' => $name, 'caller' => $caller, 'dialed' => $dialed, 'dst' => $cdrDestination, 'did' => $fromDid] as $label => $value) {
        if (!preg_match($safe, $value) || strpos($value, '..') !== false) {
            mixstereo_say('SS-HOOK-1002', "rejected unsafe {$label} argument");
            return 1;
        }
    }
    if (!preg_match('#^/[A-Za-z0-9/_.\-]+/$#', $dir) || strpos($dir, '..') !== false
        || ($uniqueId !== '' && !preg_match('/^\d+(\.\d+)?$/', $uniqueId))
        || ($cdrDuration !== '' && !preg_match('/^[0-9.]+$/', $cdrDuration))) {
        mixstereo_say('SS-HOOK-1002', 'rejected unsafe directory, uniqueid or duration argument');
        return 1;
    }
    if ($dialed === '') {
        $dialed = $fromDid !== '' ? $fromDid : $cdrDestination;
    }
    $direction = str_starts_with($name, 'in-') ? 'inbound'
        : (str_starts_with($name, 'out-') ? 'outbound' : '');

    if ($dir === '' || $name === '') {
        mixstereo_say('SS-HOOK-1001', 'missing required arguments (recording dir, CALLFILENAME)');
        return 1;
    }

    $resolveFile = static function (string $expected) use ($dir): string {
        if (is_file($dir . $expected)) {
            return $dir . $expected;
        }
        $normalized = str_replace('-', '', $expected);
        foreach (glob($dir . '*.wav') ?: [] as $candidate) {
            if (str_replace('-', '', basename($candidate)) === $normalized) {
                return $candidate;
            }
        }
        return $dir . $expected;
    };
    $base = $resolveFile("{$name}.wav");
    // Some Asterisk/FreePBX paths normalize punctuation in the MixMonitor
    // post-record arguments differently from the filenames already created.
    // Resolve only exact normalized basenames, never a loose prefix match.
    $in = $resolveFile("recv_{$name}.wav");
    $out = $resolveFile("trans_{$name}.wav");
    // Recover punctuation from the actual recording before deriving direction/metadata.
    if (is_file($in)) {
        $name = substr(pathinfo($in, PATHINFO_FILENAME), strlen('recv_'));
    } elseif (is_file($base)) {
        $name = pathinfo($base, PATHINFO_FILENAME);
    }
    $direction = str_starts_with($name, 'in-') ? 'inbound'
        : (str_starts_with($name, 'out-') ? 'outbound' : '');
    $destination = "{$dir}stereo_{$name}.wav";

    // The merged file is built as <name>.part and renamed into place only after the metadata
    // sidecar exists, so the sweeper never sees a half-written or metadata-less stereo file.
    $part = $destination . '.part';
    $mergedFrom = 'stereo';
    $trace = ['uniqueid' => $uniqueId, 'file' => basename($destination)];
    try {
        $left = Wav::read($in);
        $right = Wav::read($out);
        // Streams to disk: memory stays near the size of the two legs even for very long calls.
        Wav::mergeStereoToFile($left, $right, $part);
        unset($left, $right);
    } catch (\Throwable $exc) {
        @unlink($part);
        mixstereo_say('SS-HOOK-1003', "could not merge legs ({$exc->getMessage()})", $trace);
        // Preserve delivery when a leg is unavailable or invalid by using MixMonitor's
        // mono mix. The base filename is resolved with the same exact normalization
        // rules as the channel legs above.
        if (is_file($base) && filesize($base) > 44 && @copy($base, $part)) {
            $mergedFrom = 'mono';
            mixstereo_say('SS-HOOK-1003', 'delivering the mono mix instead of the stereo merge', $trace);
        } else {
            return 1;
        }
    }

    if ($mergedFrom === 'stereo') {
        @unlink($in);
        @unlink($out);
    }
    @unlink($base);

    // Duration: read directly from the merged file (exact); CDR duration
    // is the last-resort fallback, same rationale as the old bash script.
    $durationFile = null;
    if (is_file($part)) {
        try {
            $durationFile = Wav::read($part)->durationSeconds();
        } catch (WavError $exc) {
            // fall through to CDR fallback below
        }
    }
    if ($durationFile === null && $cdrDuration !== '') {
        $durationFile = $cdrDuration;
    }

    // started_at = UNIQUEID's epoch component (Asterisk channel creation
    // time, which is what the ingest API treats as call start).
    $startIso = null;
    $startEpochStr = strtok($uniqueId, '.');
    if ($startEpochStr !== false && ctype_digit($startEpochStr) && (int) $startEpochStr > 0) {
        $startIso = gmdate('Y-m-d\TH:i:s\Z', (int) $startEpochStr);
    }
    // Last-resort fallback for started_at: the stereo file's own mtime.
    if ($startIso === null && is_file($part)) {
        $mtime = filemtime($part);
        if ($mtime !== false) {
            $startIso = gmdate('Y-m-d\TH:i:s\Z', $mtime);
        }
    }

    $args = ['--file', $destination];
    if ($uniqueId !== '') {
        $args = array_merge($args, ['--uniqueid', $uniqueId]);
    }
    if ($caller !== '') {
        $args = array_merge($args, ['--src', $caller]);
    }
    if ($dialed !== '') {
        $args = array_merge($args, ['--dst', $dialed]);
    }
    if ($startIso !== null) {
        $args = array_merge($args, ['--start', $startIso]);
    }
    if ($durationFile !== null && $durationFile !== '') {
        $args = array_merge($args, ['--duration', (string) $durationFile]);
    }
    if ($direction !== '') {
        $args = array_merge($args, ['--direction', $direction]);
    }

    $metadata = array_filter([
        'uniqueid' => $uniqueId,
        'src' => $caller,
        'dst' => $dialed,
        'start_time' => $startIso,
        'duration_seconds' => $durationFile,
        'direction' => $direction,
        'source_filename' => basename($destination),
        'channels' => $mergedFrom === 'mono' ? 'mono' : '',
    ], function ($value) {
        return $value !== null && $value !== '';
    });
    $sidecar = $destination . '.metadata.json';
    $temporarySidecar = $sidecar . '.tmp.' . getmypid();
    $encoded = json_encode($metadata, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    if ($encoded === false || file_put_contents($temporarySidecar, $encoded, LOCK_EX) === false || !@rename($temporarySidecar, $sidecar)) {
        @unlink($temporarySidecar);
        @unlink($part);
        mixstereo_say('SS-HOOK-1004', "could not atomically create metadata sidecar {$sidecar}", $trace);
        return 1;
    }

    if ($direction === 'inbound' && $uniqueId !== '') {
        for ($attempt = 0; $attempt < 8; $attempt++) {
            $agentExtension = AnsweredExtension::lookup($uniqueId);
            if ($agentExtension !== null) {
                $metadata['agent_extension'] = $agentExtension;
                $updated = json_encode($metadata, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
                if ($updated !== false && file_put_contents($temporarySidecar, $updated, LOCK_EX) !== false
                    && @rename($temporarySidecar, $sidecar)) {
                    $args = array_merge($args, ['--agent-extension', $agentExtension]);
                } else {
                    @unlink($temporarySidecar);
                }
                break;
            }
            if ($attempt < 7) {
                sleep(1);
            }
        }
    }

    if (!@rename($part, $destination)) {
        mixstereo_say('SS-HOOK-1004', "could not move {$part} into place", $trace);
        return 1;
    }

    $php = PHP_BINARY ?: 'php';
    $uploaderScript = __DIR__ . '/uploader.php';
    $cmd = escapeshellarg($php) . ' ' . escapeshellarg($uploaderScript);
    foreach ($args as $a) {
        $cmd .= ' ' . escapeshellarg($a);
    }

    passthru($cmd, $exitCode);
    return $exitCode;
}

exit(mixstereo_main($argv));
