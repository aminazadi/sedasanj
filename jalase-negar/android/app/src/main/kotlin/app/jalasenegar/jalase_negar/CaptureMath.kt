package app.jalasenegar.jalase_negar

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** Pure decisions about how to open an external audio input (no Android classes, JVM-testable). */
internal object CapturePlan {
    /**
     * Real channels of a device. The index masks describe the physical channels, so they win;
     * the channel counts (derived from positional masks) are only used when no index mask is
     * reported.
     */
    fun channelCount(counts: IntArray, indexMasks: IntArray): Int {
        val fromMasks = indexMasks.maxOfOrNull { Integer.bitCount(it) } ?: 0
        if (fromMasks > 0) return fromMasks
        return counts.maxOrNull() ?: 0
    }

    /**
     * Sample rates to try, in order: the 16 kHz the app works at (the platform's own resampler
     * does the conversion, as for every ordinary recording app), then the device's native rate
     * decimated here with a proper low-pass filter.
     */
    fun rateCandidates(deviceRates: IntArray, target: Int): List<Int> {
        val native = when {
            deviceRates.isEmpty() -> 48000
            deviceRates.contains(48000) -> 48000
            else -> deviceRates.max()
        }
        return if (native == target) listOf(target) else listOf(target, native)
    }

    /** Positional masks only reach two channels; more need an index mask. */
    fun usesIndexMask(channels: Int) = channels > 2
}

/**
 * Per-channel level statistics for the diagnostic log: peak, RMS, number of clipped samples and
 * the correlation of the first two channels (1.0 = the same signal on both).
 */
internal class ChannelStats(private val channels: Int) {
    private val peak = IntArray(channels)
    private val sumSq = DoubleArray(channels)
    private val clipped = LongArray(channels)
    private var cross = 0.0
    private var frames = 0L

    fun add(buf: ShortArray, frameCount: Int) {
        for (f in 0 until frameCount) {
            for (c in 0 until channels) {
                val s = buf[f * channels + c].toInt()
                val a = abs(s)
                if (a > peak[c]) peak[c] = a
                if (a >= 32767) clipped[c]++
                sumSq[c] += s.toDouble() * s
            }
            if (channels >= 2) cross += buf[f * channels].toDouble() * buf[f * channels + 1]
        }
        frames += frameCount
    }

    fun correlation(): Double {
        if (channels < 2) return 0.0
        val d = sqrt(sumSq[0] * sumSq[1])
        return if (d <= 0.0) 0.0 else cross / d
    }

    fun rms(channel: Int): Double =
        if (frames == 0L) 0.0 else sqrt(sumSq[channel] / frames) / 32768.0

    fun clippedSamples(channel: Int): Long = clipped[channel]

    fun peak(channel: Int): Double = peak[channel] / 32768.0

    /** One log line, then the counters start over. Contains levels only, never audio. */
    fun report(): String {
        val sb = StringBuilder()
        for (c in 0 until channels) {
            if (c > 0) sb.append(' ')
            sb.append("ch").append(c)
                .append(" peak=").append("%.3f".format(peak(c)))
                .append(" rms=").append("%.4f".format(rms(c)))
                .append(" clip=").append(clipped[c])
        }
        if (channels >= 2) sb.append(" corr01=").append("%.3f".format(correlation()))
        peak.fill(0)
        sumSq.fill(0.0)
        clipped.fill(0)
        cross = 0.0
        frames = 0
        return sb.toString()
    }
}

/**
 * Interleaved PCM16 sample-rate conversion with a windowed-sinc low-pass (Blackman), one position
 * for all channels. The cut-off sits below the output Nyquist, so content above it is removed
 * instead of folding back as noise (what plain averaging or linear interpolation does).
 */
internal class PcmResampler(inRate: Int, outRate: Int, private val channels: Int) {
    private val passthrough = inRate == outRate
    private val ratio = inRate.toDouble() / outRate
    private val cutoff = min(0.5, 0.5 / ratio) * 0.92 // cycles per input sample
    private val half = ceil(4.0 / cutoff).toInt() // 8 lobes of the sinc
    private var hist = FloatArray(0)
    private var count = 0 // frames held in hist
    private var base = 0L // absolute index of hist frame 0
    private var next = 0.0 // absolute input position of the next output frame
    private val weights = DoubleArray(2 * half + 1)

    fun process(input: ShortArray, frames: Int): ShortArray {
        if (passthrough) return input.copyOf(frames * channels)
        append(input, frames)
        val out = ShortArray(((count / ratio).toInt() + 2) * channels)
        var n = 0
        while (true) {
            val first = max(ceil(next - half).toLong(), 0L)
            val last = floor(next + half).toLong()
            if (last >= base + count) break
            var wsum = 0.0
            for (i in first..last) {
                val t = i - next
                val w = kernel(t)
                weights[(i - first).toInt()] = w
                wsum += w
            }
            for (c in 0 until channels) {
                var acc = 0.0
                for (i in first..last) {
                    acc += weights[(i - first).toInt()] * hist[((i - base).toInt()) * channels + c]
                }
                val v = if (wsum != 0.0) acc / wsum else 0.0
                out[n++] = Math.round(v).toInt().coerceIn(-32768, 32767).toShort()
            }
            next += ratio
        }
        return out.copyOf(n)
    }

    private fun kernel(t: Double): Double {
        if (abs(t) > half) return 0.0
        val x = 2 * cutoff * t
        val sinc = if (abs(x) < 1e-9) 1.0 else sin(PI * x) / (PI * x)
        val w = 0.42 + 0.5 * cos(PI * t / half) + 0.08 * cos(2 * PI * t / half)
        return 2 * cutoff * sinc * w
    }

    private fun append(input: ShortArray, frames: Int) {
        // Drop what no future output can reach, then add the new frames.
        val keepFrom = max(floor(next - half).toLong() - 1, base)
        val drop = (keepFrom - base).toInt().coerceIn(0, count)
        val keep = count - drop
        val needed = (keep + frames) * channels
        val fresh = if (hist.size >= needed) hist else FloatArray(needed * 2)
        System.arraycopy(hist, drop * channels, fresh, 0, keep * channels)
        for (i in 0 until frames * channels) fresh[keep * channels + i] = input[i].toFloat()
        hist = fresh
        base += drop
        count = keep + frames
    }
}

/**
 * Joins the 16 kHz streams of several devices into one interleaved stream.
 *
 * The first device is the clock: every block it delivers is sent on at once, with the same number
 * of frames taken from each other device's queue. Two devices never run at exactly the same
 * speed, so a follower's queue slowly grows or empties: when it holds more than [maxBacklog]
 * frames the oldest are dropped down to [targetBacklog]; when it has too few, the gap is silence.
 * A follower that is switched off contributes silence, so the channel layout never changes.
 */
internal class StreamJoiner(
    private val channelCounts: IntArray,
    private val targetBacklog: Int = 640, // 40 ms at 16 kHz
    private val maxBacklog: Int = 2400, // 150 ms
) {
    val totalChannels = channelCounts.sum()
    private val queues = Array(channelCounts.size) { ShortArray(0) }
    private val sizes = IntArray(channelCounts.size) // samples held per follower
    private val primed = BooleanArray(channelCounts.size)
    var dropped = 0L
        private set
    var padded = 0L
        private set

    /** Audio from follower [index] (1-based among devices; 0 is the clock device). */
    @Synchronized
    fun offer(index: Int, data: ShortArray) {
        val need = sizes[index] + data.size
        if (queues[index].size < need) queues[index] = queues[index].copyOf(need * 2)
        System.arraycopy(data, 0, queues[index], sizes[index], data.size)
        sizes[index] = need
    }

    /** A block from the clock device; returns all channels interleaved, same frame count. */
    @Synchronized
    fun join(master: ShortArray): ShortArray {
        val mc = channelCounts[0]
        val frames = master.size / mc
        val out = ShortArray(frames * totalChannels)
        for (f in 0 until frames) {
            System.arraycopy(master, f * mc, out, f * totalChannels, mc)
        }
        var offset = mc
        for (d in 1 until channelCounts.size) {
            val c = channelCounts[d]
            var have = sizes[d] / c
            // Wait for a small cushion before the first use, so ordinary jitter does not pad.
            if (!primed[d] && have >= targetBacklog) primed[d] = true
            if (primed[d]) {
                if (have - frames > maxBacklog) {
                    val drop = have - frames - targetBacklog
                    consume(d, drop * c)
                    dropped += drop
                    have -= drop
                }
                val take = minOf(have, frames)
                // Missing frames (follower late) stay silent at the start of the block.
                val pad = frames - take
                padded += pad
                for (f in 0 until take) {
                    System.arraycopy(queues[d], f * c, out, (pad + f) * totalChannels + offset, c)
                }
                consume(d, take * c)
            }
            offset += c
        }
        return out
    }

    private fun consume(d: Int, samples: Int) {
        if (samples <= 0) return
        System.arraycopy(queues[d], samples, queues[d], 0, sizes[d] - samples)
        sizes[d] -= samples
    }
}
