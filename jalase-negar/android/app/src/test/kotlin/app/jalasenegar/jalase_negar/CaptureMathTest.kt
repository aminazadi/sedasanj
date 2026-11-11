package app.jalasenegar.jalase_negar

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.sin
import kotlin.math.sqrt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CaptureMathTest {
    private fun sine(freq: Double, rate: Int, frames: Int, channels: Int = 1, amp: Double = 10000.0) =
        ShortArray(frames * channels) { i ->
            (amp * sin(2 * PI * freq * (i / channels) / rate)).toInt().toShort()
        }

    private fun rms(a: ShortArray, skip: Int): Double {
        var s = 0.0
        for (i in skip until a.size) s += a[i].toDouble() * a[i]
        return sqrt(s / (a.size - skip))
    }

    private fun run(input: ShortArray, inRate: Int, channels: Int = 1): ShortArray {
        val r = PcmResampler(inRate, 16000, channels)
        // Feed in odd-sized blocks: the result must not depend on the block size.
        val out = ArrayList<Short>()
        var at = 0
        val frames = input.size / channels
        var block = 301
        while (at < frames) {
            val n = minOf(block, frames - at)
            val chunk = input.copyOfRange(at * channels, (at + n) * channels)
            for (s in r.process(chunk, n)) out.add(s)
            at += n
            block = if (block == 301) 977 else 301
        }
        return out.toShortArray()
    }

    @Test
    fun channelCountPrefersIndexMasks() {
        assertEquals(1, CapturePlan.channelCount(intArrayOf(1, 2), intArrayOf(0x1)))
        assertEquals(2, CapturePlan.channelCount(intArrayOf(1), intArrayOf(0x3)))
        assertEquals(4, CapturePlan.channelCount(intArrayOf(2), intArrayOf(0xF)))
        assertEquals(2, CapturePlan.channelCount(intArrayOf(1, 2), intArrayOf()))
        assertEquals(0, CapturePlan.channelCount(intArrayOf(), intArrayOf()))
    }

    @Test
    fun indexMaskOnlyAboveTwoChannels() {
        assertTrue(!CapturePlan.usesIndexMask(1))
        assertTrue(!CapturePlan.usesIndexMask(2))
        assertTrue(CapturePlan.usesIndexMask(3))
    }

    @Test
    fun ratesTryTargetThenNative() {
        assertEquals(listOf(16000, 48000), CapturePlan.rateCandidates(intArrayOf(44100, 48000), 16000))
        assertEquals(listOf(16000, 44100), CapturePlan.rateCandidates(intArrayOf(32000, 44100), 16000))
        assertEquals(listOf(16000, 48000), CapturePlan.rateCandidates(intArrayOf(), 16000))
        assertEquals(listOf(16000), CapturePlan.rateCandidates(intArrayOf(16000), 16000))
    }

    @Test
    fun passthroughKeepsSamples() {
        val x = sine(440.0, 16000, 640)
        assertTrue(x.contentEquals(PcmResampler(16000, 16000, 1).process(x, 640)))
    }

    @Test
    fun speechBandKeepsItsLevel() {
        val out = run(sine(1000.0, 48000, 48000), 48000)
        assertEquals(16000.0, out.size.toDouble(), 80.0)
        // RMS of a 10000-amplitude sine is 7071; allow 2% after the filter warms up.
        assertEquals(7071.0, rms(out, 200), 7071.0 * 0.02)
    }

    @Test
    fun contentAboveOutputNyquistIsRemoved() {
        // 12 kHz would fold to 4 kHz at 16 kHz if it were not filtered first.
        val out = run(sine(12000.0, 48000, 48000), 48000)
        assertTrue("aliased level ${rms(out, 200)}", rms(out, 200) < 7071.0 * 0.02)
    }

    @Test
    fun nonIntegerRatioKeepsLevelAndLength() {
        val out = run(sine(1000.0, 44100, 44100), 44100)
        assertEquals(16000.0, out.size.toDouble(), 80.0)
        assertEquals(7071.0, rms(out, 200), 7071.0 * 0.02)
    }

    @Test
    fun channelsStayApart() {
        val frames = 9600
        val inp = ShortArray(frames * 2)
        val left = sine(1000.0, 48000, frames)
        for (f in 0 until frames) inp[f * 2] = left[f] // right stays silent
        val out = run(inp, 48000, channels = 2)
        var maxRight = 0
        for (f in 0 until out.size / 2) maxRight = maxOf(maxRight, abs(out[f * 2 + 1].toInt()))
        assertEquals(0, maxRight)
        assertTrue(rms(ShortArray(out.size / 2) { out[it * 2] }, 100) > 6000)
    }

    @Test
    fun statsSeeClippingAndCorrelation() {
        val s = ChannelStats(2)
        val buf = ShortArray(200) { if (it % 4 < 2) 32767 else (-3000).toShort() }
        // Left = right on every frame.
        for (f in 0 until 100) buf[f * 2 + 1] = buf[f * 2]
        s.add(buf, 100)
        assertEquals(1.0, s.correlation(), 1e-9)
        assertTrue(s.clippedSamples(0) > 0)
        assertTrue(s.peak(0) > 0.99)
        assertTrue(s.report().contains("corr01=1.000"))
        assertEquals(0.0, s.rms(0), 0.0) // counters were reset by report()
    }

    @Test
    fun joinerInterleavesBothDevicesInStep() {
        val j = StreamJoiner(intArrayOf(2, 1), targetBacklog = 4, maxBacklog = 20)
        assertEquals(3, j.totalChannels)
        j.offer(1, shortArrayOf(7, 8, 9, 10, 11, 12))
        val out = j.join(shortArrayOf(1, 2, 3, 4))
        assertTrue(out.contentEquals(shortArrayOf(1, 2, 7, 3, 4, 8)))
        val next = j.join(shortArrayOf(5, 6))
        assertTrue(next.contentEquals(shortArrayOf(5, 6, 9)))
        assertEquals(0L, j.padded)
        assertEquals(0L, j.dropped)
    }

    @Test
    fun joinerStaysSilentWithoutAFollowerAndWhileItPrimes() {
        val j = StreamJoiner(intArrayOf(1, 1), targetBacklog = 4, maxBacklog = 20)
        assertTrue(j.join(shortArrayOf(1, 2)).contentEquals(shortArrayOf(1, 0, 2, 0)))
        j.offer(1, shortArrayOf(9, 9)) // below the cushion: not used yet
        assertTrue(j.join(shortArrayOf(3)).contentEquals(shortArrayOf(3, 0)))
    }

    @Test
    fun joinerPadsALateFollowerAtTheStartOfTheBlock() {
        val j = StreamJoiner(intArrayOf(1, 1), targetBacklog = 2, maxBacklog = 20)
        j.offer(1, shortArrayOf(5, 6))
        val out = j.join(shortArrayOf(1, 2, 3, 4))
        assertTrue(out.contentEquals(shortArrayOf(1, 0, 2, 0, 3, 5, 4, 6)))
        assertEquals(2L, j.padded)
    }

    @Test
    fun joinerDropsTheOldestWhenAFollowerRunsFast() {
        val j = StreamJoiner(intArrayOf(1, 1), targetBacklog = 2, maxBacklog = 6)
        j.offer(1, ShortArray(20) { (it + 1).toShort() })
        val out = j.join(shortArrayOf(100, 101))
        // 20 held, 2 wanted: 18 left would exceed 6, so 16 are dropped and 2 stay queued.
        assertEquals(16L, j.dropped)
        assertTrue(out.contentEquals(shortArrayOf(100, 17, 101, 18)))
        assertTrue(j.join(shortArrayOf(102, 103)).contentEquals(shortArrayOf(102, 19, 103, 20)))
    }
}
