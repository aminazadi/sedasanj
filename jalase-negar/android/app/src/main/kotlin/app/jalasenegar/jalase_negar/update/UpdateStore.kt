package app.jalasenegar.jalase_negar.update

import android.content.Context
import android.os.Process
import java.io.File
import java.util.UUID

/** An update that is downloaded and verified, waiting for a calm moment or a tap. */
data class ReadyUpdate(
    val releaseId: String,
    val versionName: String,
    val versionCode: Long,
    val size: Long,
    val sha256: String,
    val path: String,
)

/** What the Dart side last told us about the calm-moment inputs it owns. */
data class CalmSnapshot(
    val recording: Boolean,
    val pendingChunks: Int,
    val textSyncPending: Int,
    val pid: Int,
)

/** Small persistent state of the self-updater, shared by the UI process and the worker. */
class UpdateStore(context: Context) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("jalase_update", Context.MODE_PRIVATE)

    /** Anonymous random id of this installation; created once, never derived from the user. */
    @Synchronized
    fun installId(): String {
        prefs.getString(KEY_INSTALL_ID, null)?.let { return it }
        val created = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_INSTALL_ID, created).apply()
        return created
    }

    fun updatesDir(): File = File(appContext.filesDir, "updates").also { it.mkdirs() }

    fun saveCalm(recording: Boolean, pendingChunks: Int, textSyncPending: Int) {
        prefs.edit()
            .putBoolean(KEY_RECORDING, recording)
            .putInt(KEY_CHUNKS, pendingChunks)
            .putInt(KEY_TEXT, textSyncPending)
            .putInt(KEY_PID, Process.myPid())
            .apply()
    }

    /**
     * Null until the app has published once. A recording flag written by an earlier process is
     * dropped: recording lives inside the process, so a dead process cannot still be recording.
     * The unsent counters are persistent facts and stay.
     */
    fun calm(): CalmSnapshot? {
        if (!prefs.contains(KEY_PID)) return null
        val samePid = prefs.getInt(KEY_PID, -1) == Process.myPid()
        return CalmSnapshot(
            recording = samePid && prefs.getBoolean(KEY_RECORDING, false),
            pendingChunks = prefs.getInt(KEY_CHUNKS, 0),
            textSyncPending = prefs.getInt(KEY_TEXT, 0),
            pid = prefs.getInt(KEY_PID, -1),
        )
    }

    var explainerShown: Boolean
        get() = prefs.getBoolean(KEY_EXPLAINER, false)
        set(value) = prefs.edit().putBoolean(KEY_EXPLAINER, value).apply()

    var lastSeenVersionCode: Long
        get() = prefs.getLong(KEY_LAST_SEEN, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_SEEN, value).apply()

    fun ready(): ReadyUpdate? {
        val id = prefs.getString(KEY_READY_ID, null) ?: return null
        return ReadyUpdate(
            releaseId = id,
            versionName = prefs.getString(KEY_READY_NAME, "") ?: "",
            versionCode = prefs.getLong(KEY_READY_CODE, 0L),
            size = prefs.getLong(KEY_READY_SIZE, 0L),
            sha256 = prefs.getString(KEY_READY_SHA, "") ?: "",
            path = prefs.getString(KEY_READY_PATH, "") ?: "",
        )
    }

    fun saveReady(update: ReadyUpdate) {
        prefs.edit()
            .putString(KEY_READY_ID, update.releaseId)
            .putString(KEY_READY_NAME, update.versionName)
            .putLong(KEY_READY_CODE, update.versionCode)
            .putLong(KEY_READY_SIZE, update.size)
            .putString(KEY_READY_SHA, update.sha256)
            .putString(KEY_READY_PATH, update.path)
            .apply()
    }

    /** Forgets the ready update and removes its files. */
    fun clearReady() {
        prefs.edit()
            .remove(KEY_READY_ID).remove(KEY_READY_NAME).remove(KEY_READY_CODE)
            .remove(KEY_READY_SIZE).remove(KEY_READY_SHA).remove(KEY_READY_PATH)
            .apply()
        updatesDir().listFiles()?.forEach { it.delete() }
    }

    /** The install session was committed; the result is reported by the next launch of the new build. */
    fun saveAwaiting(releaseId: String, versionCode: Long, silent: Boolean) {
        prefs.edit()
            .putString(KEY_AWAIT_ID, releaseId)
            .putLong(KEY_AWAIT_CODE, versionCode)
            .putBoolean(KEY_AWAIT_SILENT, silent)
            .apply()
    }

    fun markNeededUserAction() {
        prefs.edit().putBoolean(KEY_AWAIT_SILENT, false).apply()
    }

    fun awaiting(): Triple<String, Long, Boolean>? {
        val id = prefs.getString(KEY_AWAIT_ID, null) ?: return null
        return Triple(id, prefs.getLong(KEY_AWAIT_CODE, 0L), prefs.getBoolean(KEY_AWAIT_SILENT, true))
    }

    fun clearAwaiting() {
        prefs.edit().remove(KEY_AWAIT_ID).remove(KEY_AWAIT_CODE).remove(KEY_AWAIT_SILENT).apply()
    }

    private companion object {
        const val KEY_INSTALL_ID = "install_id"
        const val KEY_RECORDING = "calm_recording"
        const val KEY_CHUNKS = "calm_chunks"
        const val KEY_TEXT = "calm_text"
        const val KEY_PID = "calm_pid"
        const val KEY_EXPLAINER = "explainer_shown"
        const val KEY_LAST_SEEN = "last_seen_version_code"
        const val KEY_READY_ID = "ready_id"
        const val KEY_READY_NAME = "ready_name"
        const val KEY_READY_CODE = "ready_code"
        const val KEY_READY_SIZE = "ready_size"
        const val KEY_READY_SHA = "ready_sha"
        const val KEY_READY_PATH = "ready_path"
        const val KEY_AWAIT_ID = "await_id"
        const val KEY_AWAIT_CODE = "await_code"
        const val KEY_AWAIT_SILENT = "await_silent"
    }
}
