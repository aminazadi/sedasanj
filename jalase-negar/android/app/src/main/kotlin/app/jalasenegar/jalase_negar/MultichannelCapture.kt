package app.jalasenegar.jalase_negar

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AudioEffect
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Captures every channel of ONE external (USB) audio input and streams interleaved little-endian
 * PCM16 at 16 kHz to Dart, like the macOS implementation.
 *
 * Per the Android docs, more than two channels need a channel INDEX mask (a positional mask caps
 * at two) and the device is chosen with setPreferredDevice. One or two channels use the ordinary
 * positional masks. The stream is asked for at 16 kHz directly (the platform resamples, as for any
 * recording app); only when that is refused the device's own rate is captured and decimated here.
 *
 * Diagnostics go to logcat under the tag JN-REC (device capabilities, the audio source and route
 * actually obtained, per-channel levels every 5 s). They contain levels only, never audio.
 * Not yet verified on hardware.
 */
class MultichannelCapture(private val context: Context) : EventChannel.StreamHandler {
    private val main = Handler(Looper.getMainLooper())
    private var sink: EventChannel.EventSink? = null
    private var threads: List<Thread> = emptyList()
    private val lock = Any()

    @Volatile private var running = false
    private var legs: List<Leg> = emptyList()
    private var deviceCallback: AudioDeviceCallback? = null
    private val failed = AtomicBoolean(false)

    companion object {
        const val TARGET_RATE = 16000
        const val TAG = "JN-REC"

        fun register(messenger: BinaryMessenger, context: Context) {
            val capture = MultichannelCapture(context)
            MethodChannel(messenger, "jalase/multichannel_capture")
                .setMethodCallHandler { call, result -> capture.handle(call, result) }
            EventChannel(messenger, "jalase/multichannel_capture/pcm").setStreamHandler(capture)
        }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink) {
        sink = events
    }

    override fun onCancel(arguments: Any?) {
        sink = null
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "listInputs" -> result.success(listInputs())
            "start" -> {
                val uids = call.argument<List<String>>("deviceUids")
                if (uids.isNullOrEmpty()) {
                    result.error("bad_args", "deviceUids is required", null)
                } else {
                    // Opening waits briefly for the route to settle, so it runs off the UI thread.
                    Thread({ start(uids, result) }, "jn-multichannel-start").start()
                }
            }
            "stop" -> {
                stop()
                result.success(null)
            }
            else -> result.notImplemented()
        }
    }

    private fun audioManager() = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private fun isExternal(d: AudioDeviceInfo) =
        d.type == AudioDeviceInfo.TYPE_USB_DEVICE ||
            d.type == AudioDeviceInfo.TYPE_USB_HEADSET ||
            d.type == AudioDeviceInfo.TYPE_USB_ACCESSORY

    private fun channelsOf(d: AudioDeviceInfo): Int =
        CapturePlan.channelCount(d.channelCounts, d.channelIndexMasks)

    private fun inputs(): List<AudioDeviceInfo> =
        audioManager().getDevices(AudioManager.GET_DEVICES_INPUTS).toList()

    private fun describe(d: AudioDeviceInfo) =
        "id=${d.id} type=${d.type} name=${d.productName} counts=${d.channelCounts.toList()} " +
            "indexMasks=${d.channelIndexMasks.toList()} rates=${d.sampleRates.toList()} " +
            "encodings=${d.encodings.toList()}"

    /**
     * The USB inputs, and beside them the phone's own microphone (one channel, flagged builtIn)
     * so both can be recorded together. Without a USB input nothing is listed: the phone's
     * microphone alone is recorded the ordinary way.
     */
    private fun listInputs(): List<Map<String, Any>> {
        val all = inputs()
        val usb = all.filter { isExternal(it) }.mapNotNull { d ->
            Log.i(TAG, "input ${describe(d)}")
            val n = channelsOf(d)
            if (n <= 0) return@mapNotNull null
            mapOf(
                "uid" to d.id.toString(),
                "name" to (d.productName?.toString()?.ifBlank { null } ?: "USB ${d.id}"),
                "channels" to n,
                "sampleRate" to (d.sampleRates.maxOrNull() ?: 48000).toDouble(),
                "builtIn" to false,
            )
        }
        if (usb.isEmpty() || Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return usb
        val phone = all.firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC } ?: return usb
        Log.i(TAG, "input ${describe(phone)}")
        return usb + mapOf(
            "uid" to phone.id.toString(),
            "name" to "Phone microphone",
            "channels" to 1,
            "sampleRate" to 48000.0,
            "builtIn" to true,
        )
    }

    private fun fail(code: String, message: String) {
        if (!failed.compareAndSet(false, true)) return
        Log.w(TAG, "capture failed: $code: $message")
        running = false
        main.post { sink?.error(code, message, null) }
    }

    private fun start(uids: List<String>, result: MethodChannel.Result) {
        val outcome = synchronized(lock) { open(uids) }
        main.post {
            if (outcome.error != null) {
                result.error(outcome.error.first, outcome.error.second, null)
            } else {
                result.success(outcome.info)
            }
        }
    }

    private class Outcome(val info: Map<String, Any>?, val error: Pair<String, String>?)

    private fun ok(info: Map<String, Any>) = Outcome(info, null)

    private fun err(code: String, message: String): Outcome {
        Log.w(TAG, "start refused: $code: $message")
        return Outcome(null, code to message)
    }

    /** One opened device. */
    private class Leg(
        val rec: AudioRecord,
        val device: AudioDeviceInfo,
        val channels: Int,
        val rate: Int,
        val effects: List<AudioEffect>,
    )

    private class OpenFailure(val code: String, message: String) : Exception(message)

    /** Opens and starts one device and checks that audio really comes from it. */
    private fun openLeg(device: AudioDeviceInfo, channels: Int, sources: List<Int>): Leg {
        val rates = CapturePlan.rateCandidates(device.sampleRates, TARGET_RATE)
        var rec: AudioRecord? = null
        var usedRate = 0
        var usedSource = 0
        var lastFailure = ""
        search@ for (rate in rates) {
            for (source in sources) {
                try {
                    val candidate = build(rate, channels, source)
                    if (candidate.state != AudioRecord.STATE_INITIALIZED) {
                        candidate.release()
                        lastFailure = "not initialized (source=$source rate=$rate)"
                        continue
                    }
                    rec = candidate
                    usedRate = rate
                    usedSource = source
                    break@search
                } catch (e: Exception) {
                    lastFailure = "${e.javaClass.simpleName}: ${e.message} (source=$source rate=$rate)"
                    Log.w(TAG, "open failed: $lastFailure")
                }
            }
        }
        val opened = rec
            ?: throw OpenFailure("format", "Cannot open $channels-channel input: $lastFailure")
        if (!opened.setPreferredDevice(device)) {
            opened.release()
            throw OpenFailure("start", "Could not select input ${device.id}")
        }
        val fx = disableEffects(opened.audioSessionId)
        try {
            opened.startRecording()
        } catch (e: Exception) {
            release(fx)
            opened.release()
            throw OpenFailure("start", "Could not start input ${device.id}: ${e.message}")
        }
        // The system routes asynchronously; never record from some other microphone silently.
        val routed = routedOf(opened)
        // A phone has several built-in microphones; any of them is the phone's microphone.
        val sameKind = routed != null && !isExternal(device) &&
            routed.type == AudioDeviceInfo.TYPE_BUILTIN_MIC
        if (routed != null && routed.id != device.id && !sameKind) {
            opened.stop()
            release(fx)
            opened.release()
            throw OpenFailure(
                "wrong_route",
                "Audio is routed to device ${routed.id} (type ${routed.type}), not ${device.id}",
            )
        }
        val actual = opened.format.channelCount.takeIf { it > 0 } ?: channels
        Log.i(
            TAG,
            "started device=${device.id} type=${device.type} source=$usedSource rate=$usedRate " +
                "asked=$channels got=$actual " +
                "routed=${routed?.let { "id=${it.id} type=${it.type}" } ?: "unknown"} " +
                "effectsOff=${fx.size} ${activeConfig(opened)}",
        )
        return Leg(opened, device, actual, usedRate, fx)
    }

    private fun routedOf(rec: AudioRecord): AudioDeviceInfo? {
        for (i in 0 until 25) {
            rec.routedDevice?.let { return it }
            Thread.sleep(20)
        }
        return null
    }

    private fun closeLeg(leg: Leg) {
        try {
            leg.rec.stop()
        } catch (_: Exception) {
        }
        release(leg.effects)
        leg.rec.release()
    }

    private fun open(uids: List<String>): Outcome {
        stopLocked()
        failed.set(false)
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return err("mic_denied", "Microphone permission denied")
        }
        val wanted = uids.map { uid ->
            inputs().firstOrNull { it.id.toString() == uid }
                ?: return err("device_missing", "Input device not found")
        }
        val usb = wanted.filter { isExternal(it) }
        val phone = wanted.firstOrNull { !isExternal(it) }
        if (usb.size != 1) {
            return err("multi_unsupported", "Exactly one USB input can be captured at a time")
        }
        val device = usb[0]
        Log.i(TAG, "opening ${describe(device)}")
        val channels = channelsOf(device)
        if (channels <= 0) return err("no_input", "Device has no input channels")

        val unprocessed = audioManager()
            .getProperty(AudioManager.PROPERTY_SUPPORT_AUDIO_SOURCE_UNPROCESSED) == "true"
        // Never MIC: on many phones it carries the maker's gain control and noise suppression.
        val usbSources = buildList {
            if (unprocessed) add(MediaRecorder.AudioSource.UNPROCESSED)
            add(MediaRecorder.AudioSource.VOICE_RECOGNITION)
        }
        val master = try {
            openLeg(device, channels, usbSources)
        } catch (e: OpenFailure) {
            return err(e.code, e.message ?: "Could not open the USB input")
        }

        // The phone's own microphone beside the receiver. Android allows a second stream on
        // another device, but a phone's audio hardware may refuse it or move the first stream;
        // then the receiver is recorded alone and the phone's channel stays silent.
        var follower: Leg? = null
        if (phone != null) {
            follower = try {
                // Tuned for speech at a distance, without the maker's call processing.
                openLeg(phone, 1, listOf(MediaRecorder.AudioSource.VOICE_RECOGNITION))
            } catch (e: OpenFailure) {
                Log.w(TAG, "phone microphone not available beside USB: ${e.code}: ${e.message}")
                null
            }
            Thread.sleep(300)
            if (!routeHolds(master)) {
                Log.w(TAG, "the phone microphone moved the USB stream; recording USB alone")
                follower?.let { closeLeg(it) }
                follower = null
                Thread.sleep(300)
                if (!routeHolds(master)) {
                    closeLeg(master)
                    return err("wrong_route", "The USB input lost its route")
                }
            }
        }

        val counts = if (phone != null) intArrayOf(master.channels, 1) else intArrayOf(master.channels)
        val joiner = StreamJoiner(counts)
        legs = listOfNotNull(master, follower)
        running = true
        registerCallbacks(master.rec, device)
        val threads = mutableListOf<Thread>()
        follower?.let { leg ->
            threads += Thread({ followerLoop(leg, joiner) }, "jn-multichannel-phone")
        }
        threads += Thread({ masterLoop(master, joiner) }, "jn-multichannel")
        threads.forEach { it.start() }
        this.threads = threads
        return ok(
            mapOf(
                "channels" to joiner.totalChannels,
                "sampleRate" to TARGET_RATE,
                "deviceRate" to master.rate,
                "phoneMic" to (follower != null),
            ),
        )
    }

    private fun routeHolds(leg: Leg): Boolean {
        val now = leg.rec.routedDevice
        return now == null || now.id == leg.device.id
    }

    private fun build(rate: Int, channels: Int, source: Int): AudioRecord {
        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(rate)
            .apply {
                if (CapturePlan.usesIndexMask(channels)) {
                    // Index mask only: a positional mask too would cap capture at 2 channels.
                    setChannelIndexMask((1 shl channels) - 1)
                } else {
                    setChannelMask(
                        if (channels == 1) AudioFormat.CHANNEL_IN_MONO
                        else AudioFormat.CHANNEL_IN_STEREO,
                    )
                }
            }
            .build()
        val minBytes = AudioRecord.getMinBufferSize(
            rate,
            if (channels == 1) AudioFormat.CHANNEL_IN_MONO else AudioFormat.CHANNEL_IN_STEREO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(0)
        val bufferBytes = maxOf(minBytes * 2, rate / 5 * channels * 2) // at least 200 ms
        return AudioRecord.Builder()
            .setAudioSource(source)
            .setAudioFormat(format)
            .setBufferSizeInBytes(bufferBytes)
            .build()
    }

    /** Switches off gain control, noise suppression and echo cancellation the system attached. */
    private fun disableEffects(session: Int): List<AudioEffect> {
        val off = mutableListOf<AudioEffect>()
        try {
            if (AutomaticGainControl.isAvailable()) {
                AutomaticGainControl.create(session)?.also { it.enabled = false; off.add(it) }
            }
            if (NoiseSuppressor.isAvailable()) {
                NoiseSuppressor.create(session)?.also { it.enabled = false; off.add(it) }
            }
            if (AcousticEchoCanceler.isAvailable()) {
                AcousticEchoCanceler.create(session)?.also { it.enabled = false; off.add(it) }
            }
        } catch (e: Exception) {
            Log.w(TAG, "could not switch effects off: ${e.message}")
        }
        return off
    }

    private fun release(fx: List<AudioEffect>) {
        for (e in fx) {
            try {
                e.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun activeConfig(rec: AudioRecord): String {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return ""
        return try {
            val c = rec.activeRecordingConfiguration ?: return "config=none"
            "config(source=${c.clientAudioSource} effects=${c.effects.size} " +
                "clientEffects=${c.clientEffects.size} device=${c.audioDevice?.type})"
        } catch (e: Exception) {
            ""
        }
    }

    private fun registerCallbacks(rec: AudioRecord, device: AudioDeviceInfo) {
        val cb = object : AudioDeviceCallback() {
            override fun onAudioDevicesRemoved(removed: Array<out AudioDeviceInfo>) {
                if (removed.any { it.id == device.id }) {
                    fail("device_lost", "The USB input was unplugged")
                }
            }
        }
        deviceCallback = cb
        audioManager().registerAudioDeviceCallback(cb, main)
        @Suppress("DEPRECATION")
        rec.addOnRoutingChangedListener(
            object : AudioRecord.OnRoutingChangedListener {
                override fun onRoutingChanged(r: AudioRecord) {
                    val now = r.routedDevice
                    if (now != null && now.id != device.id) {
                        fail("device_lost", "Audio moved to device ${now.id} (type ${now.type})")
                    }
                }
            },
            main,
        )
    }

    private fun send(out: ShortArray) {
        if (out.isEmpty()) return
        val bytes = ByteBuffer.allocate(out.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (s in out) bytes.putShort(s)
        val data = bytes.array()
        main.post { sink?.success(data) }
    }

    /** The USB receiver: the clock of the recording. Its failure ends the recording. */
    private fun masterLoop(leg: Leg, joiner: StreamJoiner) {
        val buf = ShortArray(leg.rate / 50 * leg.channels) // 20 ms
        val resampler = PcmResampler(leg.rate, TARGET_RATE, leg.channels)
        val stats = ChannelStats(joiner.totalChannels)
        var reportAt = System.nanoTime() + 5_000_000_000L
        while (running) {
            val n = leg.rec.read(buf, 0, buf.size)
            if (n < 0) {
                fail("device_lost", "Reading the USB input failed (code $n)")
                break
            }
            if (n == 0) continue
            val own = resampler.process(buf, n / leg.channels)
            if (own.isEmpty()) continue
            val out = joiner.join(own)
            stats.add(out, out.size / joiner.totalChannels)
            if (System.nanoTime() >= reportAt) {
                Log.i(
                    TAG,
                    "levels ${stats.report()} dropped=${joiner.dropped} padded=${joiner.padded}",
                )
                reportAt += 5_000_000_000L
            }
            send(out)
        }
    }

    /** The phone's microphone: feeds the joiner; if it fails its channel just goes silent. */
    private fun followerLoop(leg: Leg, joiner: StreamJoiner) {
        val buf = ShortArray(leg.rate / 50 * leg.channels)
        val resampler = PcmResampler(leg.rate, TARGET_RATE, leg.channels)
        while (running) {
            val n = leg.rec.read(buf, 0, buf.size)
            if (n < 0) {
                Log.w(TAG, "phone microphone stopped (code $n); its channel is silent from here")
                break
            }
            if (n == 0) continue
            val own = resampler.process(buf, n / leg.channels)
            if (own.isNotEmpty()) joiner.offer(1, own)
        }
    }

    fun stop() = synchronized(lock) { stopLocked() }

    private fun stopLocked() {
        running = false
        threads.forEach { it.join(500) }
        threads = emptyList()
        deviceCallback?.let {
            try {
                audioManager().unregisterAudioDeviceCallback(it)
            } catch (_: Exception) {
            }
        }
        deviceCallback = null
        legs.forEach { closeLeg(it) }
        legs = emptyList()
    }
}
