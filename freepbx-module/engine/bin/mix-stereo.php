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

function mixstereo_main(array $argv): int
{
    $dir = $argv[1] ?? '';
    $name = $argv[2] ?? '';
    $uniqueId = $argv[3] ?? '';
    $caller = $argv[4] ?? '';
    $dialed = $argv[5] ?? '';
    $cdrDuration = $argv[6] ?? '';
    $cdrDestination = $argv[7] ?? '';
    $fromDid = $argv[8] ?? '';
    if ($dialed === '') {
        $dialed = $fromDid !== '' ? $fromDid : $cdrDestination;
    }
    $direction = str_starts_with($name, 'in-') ? 'inbound'
        : (str_starts_with($name, 'out-') ? 'outbound' : '');

    if ($dir === '' || $name === '') {
        fwrite(STDERR, "mix-stereo.php: missing required arguments (recording dir, CALLFILENAME)\n");
        return 1;
    }

    $base = "{$dir}{$name}.wav";
    $in = "{$dir}recv_{$name}.wav";   // caller leg
    $out = "{$dir}trans_{$name}.wav"; // agent leg
    $destination = "{$dir}stereo_{$name}.wav";

    try {
        $left = Wav::read($in);
        $right = Wav::read($out);
        $stereo = Wav::mergeStereo($left, $right);
        Wav::write($destination, $stereo);
    } catch (WavError $exc) {
        fwrite(STDERR, "mix-stereo.php: could not merge legs into {$destination}: {$exc->getMessage()}\n");
        return 1;
    }

    @unlink($in);
    @unlink($out);
    @unlink($base);

    // Duration: read directly from the merged file (exact); CDR duration
    // is the last-resort fallback, same rationale as the old bash script.
    $durationFile = null;
    if (is_file($destination)) {
        try {
            $durationFile = Wav::read($destination)->durationSeconds();
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
    if ($startIso === null && is_file($destination)) {
        $mtime = filemtime($destination);
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
    ], function ($value) {
        return $value !== null && $value !== '';
    });
    $sidecar = $destination . '.metadata.json';
    $temporarySidecar = $sidecar . '.tmp.' . getmypid();
    $encoded = json_encode($metadata, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    if ($encoded === false || file_put_contents($temporarySidecar, $encoded, LOCK_EX) === false || !@rename($temporarySidecar, $sidecar)) {
        @unlink($temporarySidecar);
        fwrite(STDERR, "mix-stereo.php: could not atomically create metadata sidecar {$sidecar}\n");
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
