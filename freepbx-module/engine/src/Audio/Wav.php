<?php
/**
 * Audio/Wav.php - pure-PHP WAV handling, replacing sox and (for everything
 * except GSM encoding) ffmpeg. See plan.md §3.2.
 *
 * Only supports uncompressed 16-bit PCM WAV (format tag 1), which is what
 * Asterisk's MixMonitor produces - the only shape this module has ever
 * needed to handle.
 */

namespace Engine\Audio;

class WavError extends \RuntimeException
{
}

/**
 * Parsed WAV header/PCM data. $samples holds raw interleaved PCM bytes
 * (the "data" chunk contents) - never decoded into per-sample arrays,
 * so this stays fast and memory-bounded even for long calls.
 */
class WavFile
{
    public int $channels;
    public int $sampleRate;
    public int $bitsPerSample;
    public string $data; // raw PCM bytes from the "data" chunk

    public function __construct(int $channels, int $sampleRate, int $bitsPerSample, string $data)
    {
        $this->channels = $channels;
        $this->sampleRate = $sampleRate;
        $this->bitsPerSample = $bitsPerSample;
        $this->data = $data;
    }

    public function bytesPerSample(): int
    {
        return intdiv($this->bitsPerSample, 8);
    }

    public function frameSize(): int
    {
        return $this->bytesPerSample() * $this->channels;
    }

    /** Duration in seconds, exact (data_chunk_bytes / byte_rate). */
    public function durationSeconds(): float
    {
        $frameSize = $this->frameSize();
        if ($frameSize <= 0 || $this->sampleRate <= 0) {
            return 0.0;
        }
        $frames = intdiv(strlen($this->data), $frameSize);
        return $frames / $this->sampleRate;
    }
}

class Wav
{
    /**
     * Parse a WAV file from disk into a WavFile. Only PCM (format tag 1)
     * is supported; anything else raises WavError.
     */
    public static function read(string $path): WavFile
    {
        $raw = file_get_contents($path);
        if ($raw === false) {
            throw new WavError("Could not read WAV file: {$path}");
        }
        return self::parse($raw, $path);
    }

    public static function parse(string $raw, string $label = '<memory>'): WavFile
    {
        if (strlen($raw) < 12 || substr($raw, 0, 4) !== 'RIFF' || substr($raw, 8, 4) !== 'WAVE') {
            throw new WavError("Not a RIFF/WAVE file: {$label}");
        }

        $offset = 12;
        $len = strlen($raw);
        $channels = null;
        $sampleRate = null;
        $bitsPerSample = null;
        $formatTag = null;
        $data = null;

        while ($offset + 8 <= $len) {
            $chunkId = substr($raw, $offset, 4);
            $sizeUnpacked = unpack('V', substr($raw, $offset + 4, 4));
            $chunkSize = $sizeUnpacked[1];
            $bodyStart = $offset + 8;

            if ($chunkId === 'fmt ') {
                if ($bodyStart + 16 > $len) {
                    throw new WavError("Truncated fmt chunk: {$label}");
                }
                $fmt = unpack('vformatTag/vchannels/VsampleRate/VbyteRate/vblockAlign/vbitsPerSample',
                    substr($raw, $bodyStart, 16));
                $formatTag = $fmt['formatTag'];
                $channels = $fmt['channels'];
                $sampleRate = $fmt['sampleRate'];
                $bitsPerSample = $fmt['bitsPerSample'];
            } elseif ($chunkId === 'data') {
                $available = $len - $bodyStart;
                $actualSize = min($chunkSize, $available);
                $data = substr($raw, $bodyStart, $actualSize);
            }

            // Chunks are word-aligned; pad size to an even boundary.
            $advance = $chunkSize + ($chunkSize % 2);
            $offset = $bodyStart + $advance;
        }

        if ($channels === null || $sampleRate === null || $bitsPerSample === null) {
            throw new WavError("Missing fmt chunk: {$label}");
        }
        if ($data === null) {
            throw new WavError("Missing data chunk: {$label}");
        }
        // Formats 1 (PCM) and 0xFFFE (WAVE_FORMAT_EXTENSIBLE, commonly
        // still plain PCM in practice for MixMonitor output) are both
        // accepted; anything else is rejected explicitly rather than
        // silently mis-decoded.
        if ($formatTag !== 1 && $formatTag !== 0xFFFE) {
            throw new WavError("Unsupported WAV format tag {$formatTag} (only PCM is supported): {$label}");
        }
        if ($bitsPerSample !== 16) {
            throw new WavError("Unsupported bits-per-sample {$bitsPerSample} (only 16-bit PCM is supported): {$label}");
        }

        // Trim to a whole number of frames - defends against a truncated
        // data chunk (e.g. a crash mid-write) leaving a dangling odd byte.
        $frameSize = intdiv($bitsPerSample, 8) * $channels;
        if ($frameSize > 0) {
            $wholeFrames = intdiv(strlen($data), $frameSize);
            $data = substr($data, 0, $wholeFrames * $frameSize);
        }

        return new WavFile($channels, $sampleRate, $bitsPerSample, $data);
    }

    /** Build the raw bytes of a canonical 44-byte-header PCM WAV file. */
    public static function encode(WavFile $wav): string
    {
        $byteRate = $wav->sampleRate * $wav->frameSize();
        $dataSize = strlen($wav->data);
        $riffSize = 36 + $dataSize;

        $header = 'RIFF' . pack('V', $riffSize) . 'WAVE';
        $header .= 'fmt ' . pack('V', 16);
        $header .= pack(
            'vvVVvv',
            1, // PCM
            $wav->channels,
            $wav->sampleRate,
            $byteRate,
            $wav->frameSize(),
            $wav->bitsPerSample
        );
        $header .= 'data' . pack('V', $dataSize);

        return $header . $wav->data;
    }

    public static function write(string $path, WavFile $wav): void
    {
        $bytes = self::encode($wav);
        if (file_put_contents($path, $bytes) === false) {
            throw new WavError("Could not write WAV file: {$path}");
        }
    }

    /**
     * Merge two mono WAV legs into one interleaved stereo WavFile
     * (left, right - matching `sox -M leg1 leg2 out`). Both legs must
     * share sample rate and bit depth; a mismatched leg is rejected
     * rather than silently resampled. If the legs differ in length, the
     * shorter one is zero-padded (silence) to match, rather than
     * truncating the longer leg.
     */
    public static function mergeStereo(WavFile $left, WavFile $right): WavFile
    {
        if ($left->channels !== 1 || $right->channels !== 1) {
            throw new WavError('mergeStereo() expects two mono inputs');
        }
        if ($left->sampleRate !== $right->sampleRate) {
            throw new WavError(sprintf(
                'Mismatched sample rates: %d vs %d',
                $left->sampleRate,
                $right->sampleRate
            ));
        }
        if ($left->bitsPerSample !== $right->bitsPerSample) {
            throw new WavError(sprintf(
                'Mismatched bit depth: %d vs %d',
                $left->bitsPerSample,
                $right->bitsPerSample
            ));
        }

        $bytesPerSample = $left->bytesPerSample();
        $leftFrames = intdiv(strlen($left->data), $bytesPerSample);
        $rightFrames = intdiv(strlen($right->data), $bytesPerSample);
        $frames = max($leftFrames, $rightFrames);

        $leftData = str_pad($left->data, $frames * $bytesPerSample, "\x00");
        $rightData = str_pad($right->data, $frames * $bytesPerSample, "\x00");

        $out = '';
        // Interleave sample-by-sample (bytesPerSample bytes at a time).
        for ($i = 0; $i < $frames; $i++) {
            $pos = $i * $bytesPerSample;
            $out .= substr($leftData, $pos, $bytesPerSample);
            $out .= substr($rightData, $pos, $bytesPerSample);
        }

        return new WavFile(2, $left->sampleRate, $left->bitsPerSample, $out);
    }

    /**
     * Down-mix a stereo WavFile to mono by averaging each frame's two
     * 16-bit samples (replaces `ffmpeg -ac 1`).
     */
    public static function monoDownmix(WavFile $stereo): WavFile
    {
        if ($stereo->channels !== 2) {
            throw new WavError('monoDownmix() expects a stereo input');
        }
        if ($stereo->bitsPerSample !== 16) {
            throw new WavError('monoDownmix() only supports 16-bit PCM');
        }

        $bytesPerSample = 2;
        $frameSize = $bytesPerSample * 2;
        $frames = intdiv(strlen($stereo->data), $frameSize);
        $out = '';
        for ($i = 0; $i < $frames; $i++) {
            $pos = $i * $frameSize;
            $l = self::readInt16LE($stereo->data, $pos);
            $r = self::readInt16LE($stereo->data, $pos + $bytesPerSample);
            $avg = (int) round(($l + $r) / 2);
            $avg = max(-32768, min(32767, $avg));
            $out .= self::writeInt16LE($avg);
        }

        return new WavFile(1, $stereo->sampleRate, 16, $out);
    }

    private static function readInt16LE(string $data, int $offset): int
    {
        $unpacked = unpack('v', substr($data, $offset, 2))[1];
        // Convert unsigned 16-bit to signed.
        return $unpacked >= 32768 ? $unpacked - 65536 : $unpacked;
    }

    private static function writeInt16LE(int $value): string
    {
        if ($value < 0) {
            $value += 65536;
        }
        return pack('v', $value);
    }
}
