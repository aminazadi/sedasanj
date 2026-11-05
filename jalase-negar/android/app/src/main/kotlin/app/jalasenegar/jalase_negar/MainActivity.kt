package app.jalasenegar.jalase_negar

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import app.jalasenegar.jalase_negar.update.AppEnvironment
import app.jalasenegar.jalase_negar.update.AppState
import app.jalasenegar.jalase_negar.update.UpdateInstaller
import app.jalasenegar.jalase_negar.update.UpdateReporter
import app.jalasenegar.jalase_negar.update.UpdateStore
import app.jalasenegar.jalase_negar.update.UpdateWorker
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // The update channel: what the check sends the server (SDK level, ABIs, the SHA-256 of the
        // public signing certificate, an anonymous install id), plus the calm-moment inputs the
        // background installer needs from the Dart side.
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, UPDATE_CHANNEL)
            .setMethodCallHandler { call, result -> handle(call, result) }
    }

    private fun handle(call: MethodCall, result: MethodChannel.Result) {
        val store = UpdateStore(this)
        when (call.method) {
            "environment" -> {
                val cert = AppEnvironment.installedCertSha256(this)
                if (cert == null) {
                    result.error("no_certificate", "signing certificate unavailable", null)
                } else {
                    result.success(
                        mapOf(
                            "sdkInt" to Build.VERSION.SDK_INT,
                            "abis" to Build.SUPPORTED_ABIS.toList(),
                            "certSha256" to cert,
                            "installId" to store.installId(),
                        ),
                    )
                }
            }
            "setCalmState" -> {
                store.saveCalm(
                    recording = call.argument<Boolean>("recording") ?: true,
                    pendingChunks = call.argument<Int>("pendingChunks") ?: 1,
                    textSyncPending = call.argument<Int>("textSyncPending") ?: 0,
                )
                result.success(null)
            }
            "scheduleUpdates" -> {
                UpdateWorker.schedulePeriodic(this)
                result.success(null)
            }
            "runUpdatePass" -> {
                UpdateWorker.runInstallPass(this)
                result.success(null)
            }
            "canInstallPackages" -> result.success(packageManager.canRequestPackageInstalls())
            "openInstallSettings" -> result.success(openInstallSettings())
            "explainerShown" -> result.success(store.explainerShown)
            "markExplainerShown" -> {
                store.explainerShown = true
                result.success(null)
            }
            "consumeUpdatedFrom" -> result.success(consumeUpdatedFrom(store))
            "installDownloaded" -> {
                val ready = store.ready()
                if (ready == null || !packageManager.canRequestPackageInstalls()) {
                    result.success(false)
                } else {
                    // The user asked for it, so no calm-moment gate; the file is re-verified first.
                    Thread {
                        val error = UpdateInstaller.install(applicationContext, ready)
                        runOnUiThread { result.success(error == null) }
                    }.start()
                }
            }
            else -> result.notImplemented()
        }
    }

    private fun openInstallSettings(): Boolean = try {
        startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
        true
    } catch (_: Exception) {
        false
    }

    /** The version code before the latest update, once; null on a first install or a normal launch. */
    private fun consumeUpdatedFrom(store: UpdateStore): Long? {
        val current = AppEnvironment.installedVersionCode(this)
        val last = store.lastSeenVersionCode
        store.lastSeenVersionCode = current
        return if (last in 1 until current) last else null
    }

    override fun onResume() {
        super.onResume()
        AppState.inForeground = true
        Thread { UpdateReporter.flushInstalled(applicationContext) }.start()
    }

    override fun onPause() {
        AppState.inForeground = false
        super.onPause()
    }

    private companion object {
        const val UPDATE_CHANNEL = "app.jalasenegar.jalase_negar/update"
    }
}
