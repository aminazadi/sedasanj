package app.jalasenegar.jalase_negar.update

import android.content.Context
import android.os.Build
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Sends the anonymous outcome of an update attempt: a random install id, the release id, the
 * result, the Android level and the phone maker. No account, token or other identity is attached.
 */
object UpdateReporter {
    private const val PATH = "/v1/jalase-negar/android/update/report"

    /** Blocking; call from a worker or a background thread. Failures are ignored on purpose. */
    fun send(
        context: Context,
        releaseId: String,
        result: String,
        errorCode: String? = null,
        silent: Boolean = false,
    ) {
        val body = JSONObject()
            .put("install_id", UpdateStore(context).installId())
            .put("release_id", releaseId)
            .put("result", result)
            .put("sdk_int", Build.VERSION.SDK_INT)
            .put("manufacturer", AppEnvironment.manufacturer())
            .put("silent", silent)
        if (errorCode != null) body.put("error_code", errorCode)
        var connection: HttpURLConnection? = null
        try {
            connection = URL(UPDATE_ORIGIN + PATH).openConnection() as HttpURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10_000
            connection.readTimeout = 10_000
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(body.toString().toByteArray()) }
            connection.responseCode
        } catch (_: Exception) {
            // Reporting is best effort and must never affect the update itself.
        } finally {
            connection?.disconnect()
        }
    }

    /**
     * After an install the process restarts as the new build: report "installed" once the running
     * version reaches the one we were installing. Blocking.
     */
    fun flushInstalled(context: Context) {
        val store = UpdateStore(context)
        val (releaseId, code, silent) = store.awaiting() ?: return
        if (AppEnvironment.installedVersionCode(context) < code) return
        store.clearAwaiting()
        send(context, releaseId, "installed", silent = silent)
    }
}
