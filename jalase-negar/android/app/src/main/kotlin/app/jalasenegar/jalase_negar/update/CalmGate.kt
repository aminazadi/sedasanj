package app.jalasenegar.jalase_negar.update

/** Everything the "calm moment" decision looks at. */
data class CalmInputs(
    val recording: Boolean,
    val pendingChunks: Int,
    val textSyncPending: Int,
    val appInForeground: Boolean,
    val freeBytes: Long,
    val apkBytes: Long,
    val batteryPercent: Int,
    val charging: Boolean,
)

data class CalmDecision(val calm: Boolean, val reason: String?)

/**
 * Installing replaces the app and kills its process, so it may only happen when nothing is
 * running that would be lost: no recording, nothing left to upload or sync, the app in the
 * background, enough free space (at least twice the APK) and a charged or charging battery.
 */
object CalmGate {
    const val MIN_BATTERY_PERCENT = 30

    fun check(input: CalmInputs): CalmDecision = when {
        input.recording -> CalmDecision(false, "recording")
        input.pendingChunks > 0 -> CalmDecision(false, "upload_pending")
        input.textSyncPending > 0 -> CalmDecision(false, "text_sync_pending")
        input.appInForeground -> CalmDecision(false, "foreground")
        input.freeBytes < input.apkBytes * 2 -> CalmDecision(false, "low_storage")
        !input.charging && input.batteryPercent < MIN_BATTERY_PERCENT ->
            CalmDecision(false, "low_battery")
        else -> CalmDecision(true, null)
    }
}
