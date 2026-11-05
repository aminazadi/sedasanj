package app.jalasenegar.jalase_negar.update

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.StatFs
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/**
 * Background update pass: check the server, download and verify, and install at a calm moment.
 * Runs about every 8 hours on an unmetered network with a battery that is not low, and once
 * more (install only) when the app goes to the background.
 */
class UpdateWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        val store = UpdateStore(applicationContext)
        try {
            UpdateReporter.flushInstalled(applicationContext)
            if (!applicationContext.packageManager.canRequestPackageInstalls()) return Result.success()
            val installOnly = inputData.getBoolean(KEY_INSTALL_ONLY, false)
            var ready = store.ready()?.takeIf { isStillUseful(it) }
            if (ready == null) {
                store.clearReady()
                if (installOnly) return Result.success()
                ready = checkAndDownload(store) ?: return Result.success()
            }
            val decision = CalmGate.check(calmInputs(store, ready))
            if (!decision.calm) return Result.success()
            val error = UpdateInstaller.install(applicationContext, ready)
            if (error != null) {
                UpdateReporter.send(applicationContext, ready.releaseId, "failed", error)
            }
        } catch (_: Exception) {
            // The next period tries again; a background pass must never crash the app.
        }
        return Result.success()
    }

    private fun isStillUseful(ready: ReadyUpdate): Boolean =
        ready.versionCode > AppEnvironment.installedVersionCode(applicationContext) &&
            File(ready.path).isFile

    private fun calmInputs(store: UpdateStore, ready: ReadyUpdate): CalmInputs {
        val snapshot = store.calm()
        val stat = StatFs(applicationContext.filesDir.path)
        val battery = applicationContext.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, 100) ?: 100
        val status = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        return CalmInputs(
            // Never published yet means the app has not run since this build: assume nothing is
            // known and wait, rather than guess a quiet state.
            recording = snapshot?.recording ?: true,
            pendingChunks = snapshot?.pendingChunks ?: 1,
            textSyncPending = snapshot?.textSyncPending ?: 0,
            appInForeground = AppState.inForeground,
            freeBytes = stat.availableBytes,
            apkBytes = ready.size,
            batteryPercent = if (level >= 0 && scale > 0) level * 100 / scale else 0,
            charging = charging,
        )
    }

    private fun checkAndDownload(store: UpdateStore): ReadyUpdate? {
        val offer = fetchOffer(store) ?: return null
        val installed = AppEnvironment.installedVersionCode(applicationContext)
        if (offer.versionCode <= installed || offer.minSdk > Build.VERSION.SDK_INT) return null
        val stat = StatFs(applicationContext.filesDir.path)
        if (stat.availableBytes < offer.size * 2) return null
        val target = File(store.updatesDir(), "update-${offer.id}.apk")
        when (val result = ApkDownloader().download(offer, target)) {
            is DownloadResult.Ok -> Unit
            is DownloadResult.ChecksumMismatch -> {
                UpdateReporter.send(applicationContext, offer.id, "failed", UpdateError.CHECKSUM_MISMATCH)
                return null
            }
            is DownloadResult.Failed -> return null
        }
        val problem = UpdateInstaller.verifyArchive(applicationContext, target)
        if (problem != null) {
            target.delete()
            UpdateReporter.send(applicationContext, offer.id, "failed", problem)
            return null
        }
        val ready = ReadyUpdate(offer.id, offer.versionName, offer.versionCode, offer.size, offer.sha256, target.path)
        store.saveReady(ready)
        UpdateReporter.send(applicationContext, offer.id, "downloaded")
        return ready
    }

    private fun fetchOffer(store: UpdateStore): UpdateOffer? {
        val context = applicationContext
        val query = listOf(
            "version_code" to AppEnvironment.installedVersionCode(context).toString(),
            "sdk_int" to Build.VERSION.SDK_INT.toString(),
            "abis" to Build.SUPPORTED_ABIS.joinToString(","),
            "cert_sha256" to (AppEnvironment.installedCertSha256(context) ?: return null),
            "install_id" to store.installId(),
        ).joinToString("&") { (key, value) -> "$key=${URLEncoder.encode(value, "UTF-8")}" }
        var connection: HttpURLConnection? = null
        try {
            connection = URL("$UPDATE_ORIGIN/v1/jalase-negar/android/update?$query")
                .openConnection() as HttpURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15_000
            connection.readTimeout = 15_000
            connection.setRequestProperty("Accept", "application/json")
            if (connection.responseCode != 200) return null
            val body = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            if (body.isNull("update")) return null
            val update = body.getJSONObject("update")
            return UpdateOffer.parse(
                id = update.optString("id"),
                versionName = update.optString("version"),
                versionCode = update.optLong("version_code", 0),
                size = update.optLong("size", 0),
                sha256 = update.optString("sha256"),
                minSdk = update.optInt("min_sdk", 0),
                downloadPath = update.optString("download_path"),
                mandatory = update.optBoolean("mandatory", false),
            )
        } catch (_: Exception) {
            return null
        } finally {
            connection?.disconnect()
        }
    }

    companion object {
        private const val PERIODIC = "jalase_update_periodic"
        private const val ONCE = "jalase_update_once"
        private const val KEY_INSTALL_ONLY = "install_only"

        /** Every ~8 hours (the system may stretch it within a 4 hour flex), Wi-Fi only. */
        fun schedulePeriodic(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.UNMETERED)
                .setRequiresBatteryNotLow(true)
                .build()
            val request = PeriodicWorkRequestBuilder<UpdateWorker>(8, TimeUnit.HOURS, 4, TimeUnit.HOURS)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
        }

        /** One extra pass that only installs an already downloaded update; needs no network. */
        fun runInstallPass(context: Context) {
            val constraints = Constraints.Builder().setRequiresBatteryNotLow(true).build()
            val request = OneTimeWorkRequestBuilder<UpdateWorker>()
                .setConstraints(constraints)
                .setInputData(workDataOf(KEY_INSTALL_ONLY to true))
                .setInitialDelay(20, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(ONCE, ExistingWorkPolicy.REPLACE, request)
        }
    }
}
