<?php
/**
 * Staging.php - packages a recording for upload and produces the local
 * mono archive copy. Ported from common.py's stage_recording() /
 * transcode_archive() / _create_passworded_zip() / _check_staged_size().
 *
 * Replaces `sox` with the pure-PHP Wav::mergeStereo()/monoDownmix(), and
 * uses the system `ffmpeg` binary to encode the local mono archive copy
 * into archive.format for every format except gsm (mp3, ogg, opus, ...
 * - whatever ffmpeg can mux).
 *
 * archive.format = "gsm" (the default) is the one exception: ffmpeg can
 * only encode GSM via its external `libgsm` build option, and no known
 * pre-built static ffmpeg distribution (johnvansickle's, BtbN's) enables
 * it, so shelling out to a vendored ffmpeg binary for gsm always fails
 * with "Unknown encoder 'libgsm'" (exit 8). GSM gets its own tiny
 * dedicated encoder instead - see gsmEncoderCommand()'s docblock - which
 * is what plan.md §3.3 originally proposed before that step got skipped
 * in favor of routing everything through ffmpeg.
 *
 * AES-256 ZIP staging still uses the vendored static `7zzs` binary
 * (bin/7zip/7zzs-<arch>) - PHP core's ZipArchive cannot produce AES-256
 * (WinZip-AE), only the legacy weak ZipCrypto. See plan.md §3.3.
 */

namespace Engine;

use Engine\Audio\Wav;

class StagingError extends \RuntimeException
{
}

class Staging
{
    /** Root of the engine tree (…/engine), used to locate bin/7zip. */
    private static function engineRoot(): string
    {
        return dirname(__DIR__);
    }

    private static function archTag(): string
    {
        $machine = php_uname('m');
        if (in_array($machine, ['x86_64', 'amd64'], true)) {
            return 'x86_64';
        }
        if (in_array($machine, ['aarch64', 'arm64'], true)) {
            return 'aarch64';
        }
        return $machine;
    }

    private static function vendoredBinary(string $subdir, string $prefix): ?string
    {
        $path = self::engineRoot() . "/bin/{$subdir}/{$prefix}-" . self::archTag();
        return is_file($path) && is_executable($path) ? $path : null;
    }

    /**
     * Path to the ffmpeg binary used to encode the local mono archive
     * copy. Resolution order:
     *   1. ARU_FFMPEG_PATH environment variable, if set - lets a
     *      deployment point at an arbitrary binary/build explicitly.
     *   2. A vendored per-architecture binary at bin/ffmpeg/ffmpeg-<arch>
     *      (same convention as sevenZipPath()/bin/7zip/7zzs-<arch>) -
     *      lets a box with no internet access or no package manager still
     *      work, by dropping in a static build.
     *   3. Plain "ffmpeg", resolved via $PATH - the normal case on a box
     *      with the system package installed.
     */
    public static function ffmpegPath(): string
    {
        $override = getenv('ARU_FFMPEG_PATH');
        if ($override !== false && $override !== '') {
            return $override;
        }
        $vendored = self::vendoredBinary('ffmpeg', 'ffmpeg');
        if ($vendored !== null) {
            return $vendored;
        }
        return 'ffmpeg';
    }

    public static function sevenZipPath(): ?string
    {
        return self::vendoredBinary('7zip', '7zzs');
    }

    /**
     * Command (as an argv array) for a dedicated GSM 06.10 encoder used
     * for archive.format = "gsm" ONLY, instead of ffmpeg - see the class
     * docblock above for why ffmpeg can't do this. GSM 06.10 itself is
     * tiny and dependency-free (~50 KB), so it gets its own minimal
     * encoder rather than a full ffmpeg rebuild with --enable-libgsm.
     *
     * Resolution order:
     *   1. ARU_GSM_ENCODER_PATH env var - an explicit path to a binary
     *      that reads raw 16-bit LE mono 8000 Hz PCM on stdin and writes
     *      concatenated 33-byte GSM 06.10 frames on stdout (the same
     *      contract as bin/gsm/gsm-encode.c in this repo).
     *   2. A vendored per-architecture binary at bin/gsm/gsm-encode-<arch>
     *      - build it with bin/gsm/build.sh on a box of that architecture
     *      (needs libgsm1-dev + gcc). This is the exact same public-domain
     *      GSM 06.10 reference implementation (Jutta Degener/Carsten
     *      Bormann, quut.com/gsm) that Asterisk itself vendors under
     *      codecs/gsm/ and links into format_gsm - output is verified
     *      byte-identical to Asterisk's own native .gsm files.
     *   3. Plain "gsm-encode", resolved via $PATH.
     *   4. The system "toast" CLI (from the gsm-utils / libgsm-tools OS
     *      package - e.g. `apt-get install gsm-utils` on Debian/Ubuntu),
     *      run as `toast -l -c`, if present. Same underlying library,
     *      byte-identical output - the fastest fix on a box that already
     *      has (or can get) package-manager/internet access, no vendoring
     *      needed.
     *
     * Returns null if none of the above are available, so the caller can
     * raise one clear, actionable error instead of shelling out to
     * something that doesn't exist.
     */
    public static function gsmEncoderCommand(): ?array
    {
        $override = getenv('ARU_GSM_ENCODER_PATH');
        if ($override !== false && $override !== '') {
            return [$override];
        }
        $vendored = self::vendoredBinary('gsm', 'gsm-encode');
        if ($vendored !== null) {
            return [$vendored];
        }
        if (self::binaryOnPath('gsm-encode')) {
            return ['gsm-encode'];
        }
        if (self::binaryOnPath('toast')) {
            return ['toast', '-l', '-c'];
        }
        return null;
    }

    private static function binaryOnPath(string $name): bool
    {
        $which = trim((string) shell_exec('command -v ' . escapeshellarg($name) . ' 2>/dev/null'));
        return $which !== '';
    }

    /**
     * Copy the recording into the pending folder, packaging it the way
     * /v1/ingest/calls expects.
     *
     * upload.format selects wav, gzip, or zip. A non-empty archive password
     * turns ZIP into AES-256 ZIP without changing local archive settings.
     *
     * The local archive copy (transcodeArchive) is never encrypted/gzipped.
     */
    public static function stageRecording(array $cfg, string $sourcePath, ?\Closure $log = null): string
    {
        $log = $log ?? function (string $msg) {};
        $stagingDir = $cfg['queue']['spool_dir'];
        if (!is_dir($stagingDir)) {
            mkdir($stagingDir, 0755, true);
        }
        $basename = basename($sourcePath);
        $stagingName = substr(hash('sha256', realpath($sourcePath) ?: $sourcePath), 0, 16) . '-' . $basename;
        $password = $cfg['general']['archive_password'] ?? '';
        $format = $cfg['upload']['format'] ?? 'wav';

        if ($format === 'zip') {
            $dest = "{$stagingDir}/{$stagingName}.zip";
            if ($password !== '') {
                $log("Staging {$sourcePath} as AES-256 passworded ZIP -> {$dest}");
                self::createZip($sourcePath, $dest, $password);
            } else {
                $log("Staging {$sourcePath} as ZIP -> {$dest}");
                self::createZip($sourcePath, $dest, null);
            }
            self::checkStagedSize($dest);
        } elseif ($format === 'gzip') {
            $dest = "{$stagingDir}/{$stagingName}.gz";
            $in = fopen($sourcePath, 'rb');
            $out = gzopen($dest, 'wb9');
            if ($in === false || $out === false) {
                throw new StagingError("Could not gzip {$sourcePath} -> {$dest}");
            }
            while (!feof($in)) {
                gzwrite($out, fread($in, 1024 * 1024));
            }
            fclose($in);
            gzclose($out);
            self::checkStagedSize($dest);
        } else {
            $dest = "{$stagingDir}/{$stagingName}";
            if (!copy($sourcePath, $dest)) {
                throw new StagingError("Could not copy {$sourcePath} -> {$dest}");
            }
            self::checkStagedSize($dest);
        }

        return $dest;
    }

    public static function prepareVoicemail(array $cfg, string $sourcePath, string $identity, ?\Closure $log = null): string
    {
        $directory = $cfg['queue']['spool_dir'];
        if (!is_dir($directory) && !mkdir($directory, 0750, true) && !is_dir($directory)) {
            throw new StagingError("Could not create voicemail staging directory {$directory}");
        }
        $canonical = rtrim($directory, '/') . '/.voicemail-' . substr(hash('sha256', $identity), 0, 32) . '.wav';
        $command = sprintf(
            '%s -nostdin -hide_banner -loglevel error -y -i %s -map 0:a:0 -vn -ac 1 -ar 8000 -c:a pcm_s16le -f wav %s 2>&1',
            escapeshellarg(self::ffmpegPath()),
            escapeshellarg($sourcePath),
            escapeshellarg($canonical)
        );
        exec($command, $output, $exitCode);
        if ($exitCode !== 0 || !is_file($canonical) || filesize($canonical) <= 44) {
            @unlink($canonical);
            $detail = implode("\n", array_slice($output, -10));
            throw new StagingError("Could not convert voicemail audio to mono PCM WAV: {$detail}");
        }
        try {
            $staged = self::stageRecording($cfg, $canonical, $log);
        } finally {
            @unlink($canonical);
        }
        return $staged;
    }

    private static function checkStagedSize(string $path): void
    {
        $size = filesize($path);
        if ($size !== false && $size > Config::MAX_COMPRESSED_BYTES) {
            throw new UploadError(
                "Staged file {$path} is {$size} bytes; API limit is " . Config::MAX_COMPRESSED_BYTES . ' bytes',
                null,
                false,
                false,
                'SS-STG-1005',
                ['bytes' => $size]
            );
        }
    }

    /**
     * Create an AES-256 encrypted ZIP containing exactly one root-level
     * entry (the source file), using the vendored 7zzs binary.
     *
     * The ingest API rejects ZIPs that:
     *   - contain more than one entry / directories / links / nested paths
     *   - contain anything other than a single .wav
     *   - use anything other than AES-256 (no ZipCrypto, no AES-128)
     * Running 7zzs from the source directory and passing only the
     * basename guarantees a single root-level entry.
     */
    private static function createZip(string $sourcePath, string $destPath, ?string $password): void
    {
        $sevenZip = self::sevenZipPath();
        if ($sevenZip === null) {
            throw new StagingError(
                'No vendored 7zzs binary found for architecture ' . self::archTag() .
                ' (bin/7zip/7zzs-' . self::archTag() . '); ' .
                'vendor the binary for this architecture'
            );
        }

        $srcDir = dirname(realpath($sourcePath) ?: $sourcePath);
        $srcName = basename($sourcePath);
        $destAbs = self::absPath($destPath);

        $passwordArgs = $password !== null && $password !== ''
            ? ' -mem=AES256 -p' . escapeshellarg($password)
            : '';
        $cmd = sprintf(
            'cd %s && %s a -tzip -y%s %s %s 2>&1',
            escapeshellarg($srcDir),
            escapeshellarg($sevenZip),
            $passwordArgs,
            escapeshellarg($destAbs),
            escapeshellarg($srcName)
        );

        exec($cmd, $outputLines, $exitCode);

        if ($exitCode !== 0) {
            @unlink($destAbs);
            $tail = implode("\n", array_slice($outputLines, -20));
            throw new StagingError("7zzs failed (exit {$exitCode}) creating {$destAbs}: {$tail}");
        }
        if (!is_file($destAbs) || filesize($destAbs) === 0) {
            throw new StagingError("7zzs reported success but {$destAbs} is missing/empty");
        }
    }

    private static function absPath(string $path): string
    {
        $real = realpath($path);
        if ($real !== false) {
            return $real;
        }
        // File doesn't exist yet (destination); resolve its directory only.
        $dir = realpath(dirname($path)) ?: dirname($path);
        return rtrim($dir, '/') . '/' . basename($path);
    }

    /**
     * Produce the local mono archive copy from the merged stereo WAV.
     * archive.format = "wav" is written directly via the pure-PHP
     * downmix/encoder (no external dependency needed for plain PCM WAV).
     * "gsm" (the default) goes through the dedicated encoder in
     * encodeGsm()/gsmEncoderCommand(). Every other format - "mp3", "ogg",
     * "opus", etc. - is produced by shelling out to the system `ffmpeg`
     * binary, so any format ffmpeg can mux is supported there.
     */
    public static function transcodeArchive(array $cfg, string $originalStereoPath, ?\Closure $log = null): string
    {
        $directory = dirname($originalStereoPath);
        $base = basename($originalStereoPath);
        if (!str_starts_with($base, 'stereo_')) {
            throw new \InvalidArgumentException("Expected a 'stereo_<n>.<ext>' filename, got: {$base}");
        }
        $stem = pathinfo(substr($base, strlen('stereo_')), PATHINFO_FILENAME);
        $format = strtolower(trim($cfg['archive']['format']));
        $archivePath = "{$directory}/{$stem}.{$format}";

        $stereo = Wav::read($originalStereoPath);
        // The mono fallback of the recording hook delivers MixMonitor's own mono mix under a stereo_ name.
        $mono = $stereo->channels === 1 ? $stereo : Wav::monoDownmix($stereo);
        if ($mono->data === '') {
            throw new StagingError("Recording has no audio samples: {$originalStereoPath}");
        }

        if ($format === 'wav') {
            // Plain mono PCM WAV: no external dependency needed.
            Wav::write($archivePath, $mono);
            return $archivePath;
        }

        // GSM 06.10 is defined at 8000 Hz; ffmpeg would otherwise resample
        // it silently, and MixMonitor recordings are already 8000 Hz in
        // practice, so a mismatch is rejected clearly here rather than
        // silently resampled.
        if ($format === 'gsm' && $mono->sampleRate !== 8000) {
            throw new StagingError(
                "GSM encoding requires an 8000 Hz source; got {$mono->sampleRate} Hz for {$originalStereoPath}"
            );
        }

        // gsm never goes through ffmpeg - see the class docblock and
        // gsmEncoderCommand() for why. No temp WAV needed either: the
        // dedicated encoder wants headerless raw PCM, and $mono->data
        // already is that.
        if ($format === 'gsm') {
            self::encodeGsm($mono, $archivePath, $originalStereoPath);
            return $archivePath;
        }

        $tmpMono = $directory . '/.tmp_mono_' . $stem . '.wav';
        Wav::write($tmpMono, $mono);

        $ffmpeg = self::ffmpegPath();
        $cmd = sprintf(
            '%s -y -i %s -ac 1 -ar %d %s 2>&1',
            escapeshellarg($ffmpeg),
            escapeshellarg($tmpMono),
            $mono->sampleRate,
            escapeshellarg($archivePath)
        );
        exec($cmd, $outputLines, $exitCode);
        @unlink($tmpMono);

        if ($exitCode !== 0) {
            $tail = implode("\n", array_slice($outputLines, -20));
            throw new StagingError(
                "ffmpeg failed (exit {$exitCode}) encoding {$originalStereoPath} to .{$format}: {$tail}. " .
                'Is ffmpeg installed and on $PATH?'
            );
        }
        if (!is_file($archivePath) || filesize($archivePath) === 0) {
            throw new StagingError("ffmpeg reported success but {$archivePath} is missing/empty");
        }

        return $archivePath;
    }

    /**
     * Encode $mono straight to raw GSM 06.10 via gsmEncoderCommand() -
     * no ffmpeg. Both ends are redirected straight to real files
     * (a temp raw-PCM input, $archivePath as the output) rather than
     * piped through PHP: a long call recording can be several MB of
     * PCM, and writing that much to a pipe from PHP while not
     * concurrently draining the encoder's stdout would deadlock once
     * the OS pipe buffer (typically 64 KB) fills up. File redirection
     * sidesteps that entirely - same pattern createPasswordedZip() and
     * the ffmpeg path above already use (exec() to a real destination
     * file), just via proc_open() since we also want the encoder's
     * stderr captured for the error message.
     */
    private static function encodeGsm(\Engine\Audio\WavFile $mono, string $archivePath, string $originalStereoPath): void
    {
        $command = self::gsmEncoderCommand();
        if ($command === null) {
            throw new StagingError(
                'No GSM 06.10 encoder available for archive.format = "gsm": no ARU_GSM_ENCODER_PATH ' .
                'override, no vendored bin/gsm/gsm-encode-' . self::archTag() . ', and no gsm-encode or ' .
                'toast on $PATH. Fix by either (a) apt-get install gsm-utils (provides toast - ' .
                'Debian/Ubuntu), (b) running bin/gsm/build.sh on a ' . self::archTag() . ' box to produce ' .
                'bin/gsm/gsm-encode-' . self::archTag() . ', or (c) setting archive.format to something ' .
                'ffmpeg handles natively (wav, mp3, ogg, opus).'
            );
        }

        $directory = dirname($archivePath);
        $tmpRaw = $directory . '/.tmp_gsm_raw_' . bin2hex(random_bytes(4)) . '.pcm';
        if (file_put_contents($tmpRaw, $mono->data) === false) {
            throw new StagingError("Could not write temp raw PCM for GSM encoding: {$tmpRaw}");
        }

        $cmdLine = implode(' ', array_map('escapeshellarg', $command));
        $descriptors = [
            0 => ['file', $tmpRaw, 'r'],
            1 => ['file', $archivePath, 'w'],
            2 => ['pipe', 'w'],
        ];
        $process = proc_open($cmdLine, $descriptors, $pipes);
        if (!is_resource($process)) {
            @unlink($tmpRaw);
            throw new StagingError("Could not start GSM encoder ({$cmdLine}) for {$originalStereoPath}");
        }

        $stderr = trim((string) stream_get_contents($pipes[2]));
        fclose($pipes[2]);
        $exitCode = proc_close($process);
        @unlink($tmpRaw);

        if ($exitCode !== 0) {
            @unlink($archivePath);
            throw new StagingError(
                "GSM encoder ({$cmdLine}) failed (exit {$exitCode}) encoding {$originalStereoPath}" .
                ($stderr !== '' ? ": {$stderr}" : '')
            );
        }
        if (!is_file($archivePath) || filesize($archivePath) === 0) {
            throw new StagingError("GSM encoder reported success but {$archivePath} is missing/empty");
        }
    }

    /**
     * Stage + archive a merged stereo recording, deleting the original
     * once both artefacts exist. Mirrors common.prepare_recording().
     *
     * @return array [$stagedPath, $archivePath]
     */
    public static function prepareRecording(array $cfg, string $originalStereoPath, ?\Closure $log = null): array
    {
        $log = $log ?? function (string $msg) {};
        $stagedPath = self::stageRecording($cfg, $originalStereoPath, $log);
        try {
            $archivePath = self::transcodeArchive($cfg, $originalStereoPath, $log);
        } catch (\Throwable $e) {
            @unlink($stagedPath);
            throw $e;
        }

        $sourceSidecar = $originalStereoPath . '.metadata.json';
        if (is_file($sourceSidecar)) {
            $metadata = json_decode((string) @file_get_contents($sourceSidecar), true);
            if (is_array($metadata)) {
                $recovery = [
                    'metadata' => $metadata,
                    'archive_path' => $archivePath,
                    'source_path' => $originalStereoPath,
                    'created_at' => gmdate('c'),
                ];
                $sidecarPath = $stagedPath . '.metadata.json';
                $temporary = $sidecarPath . '.tmp.' . getmypid();
                $encoded = json_encode($recovery, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
                if ($encoded === false || file_put_contents($temporary, $encoded, LOCK_EX) === false
                    || !@rename($temporary, $sidecarPath)) {
                    @unlink($temporary);
                    @unlink($stagedPath);
                    @unlink($archivePath);
                    throw new StagingError("Could not create staged metadata sidecar {$sidecarPath}");
                }
            }
        }

        if (!@unlink($originalStereoPath)) {
            $log("Could not remove original stereo file {$originalStereoPath} after staging/archiving");
        }

        return [$stagedPath, $archivePath];
    }
}
