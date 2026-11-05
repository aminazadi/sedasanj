package app.jalasenegar.jalase_negar.update

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import java.io.File

/**
 * Installs a verified APK with [PackageInstaller]. On Android 12+ the session asks not to
 * require user action; whether the phone honours that depends on the installer of record, the
 * OEM and the system policy, so the result receiver falls back to a one-tap notification.
 */
object UpdateInstaller {
    const val ACTION_RESULT = "app.jalasenegar.jalase_negar.UPDATE_INSTALL_RESULT"
    private const val CHANNEL_ID = "app_update"
    private const val NOTIFICATION_ID = 7301

    /** Re-checks the file and its signature against the running app, then commits a session. */
    fun install(context: Context, ready: ReadyUpdate): String? {
        val store = UpdateStore(context)
        val apk = File(ready.path)
        val offerLike = UpdateOffer(
            ready.releaseId, ready.versionName, ready.versionCode, ready.size, ready.sha256, 0, "", false,
        )
        if (!ApkDownloader.verifies(apk, offerLike)) {
            store.clearReady()
            return UpdateError.CHECKSUM_MISMATCH
        }
        val problem = verifyArchive(context, apk)
        if (problem != null) {
            store.clearReady()
            return problem
        }
        if (!context.packageManager.canRequestPackageInstalls()) return UpdateError.INSTALL_BLOCKED
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        params.setSize(apk.length())
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        }
        var sessionId = -1
        try {
            sessionId = installer.createSession(params)
            installer.openSession(sessionId).use { session ->
                apk.inputStream().use { input ->
                    session.openWrite("base.apk", 0, apk.length()).use { output ->
                        input.copyTo(output, 64 * 1024)
                        session.fsync(output)
                    }
                }
                store.saveAwaiting(ready.releaseId, ready.versionCode, silent = true)
                val intent = Intent(context, UpdateInstallReceiver::class.java).setAction(ACTION_RESULT)
                // The system fills in the status extras, so the intent must be mutable.
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
                val pending = PendingIntent.getBroadcast(context, sessionId, intent, flags)
                session.commit(pending.intentSender)
            }
            return null
        } catch (_: Exception) {
            if (sessionId >= 0) {
                try {
                    installer.abandonSession(sessionId)
                } catch (_: Exception) {
                }
            }
            return UpdateError.INSTALL_BLOCKED
        }
    }

    /** Error code when the file must not replace the running app (downgrade, other signer), else null. */
    fun verifyArchive(context: Context, apk: File): String? {
        val pm = context.packageManager
        val archive = AppEnvironment.archiveInfo(pm, apk.path)
            ?: return UpdateError.CHECKSUM_MISMATCH
        return UpdatePolicy.archiveProblem(
            installedVersionCode = AppEnvironment.installedVersionCode(context),
            installedCertSha256 = AppEnvironment.installedCertSha256(context),
            archivePackage = archive.packageName,
            archiveVersionCode = AppEnvironment.versionCode(archive),
            archiveCertSha256 = AppEnvironment.fromPackageInfo(archive),
        )
    }

    fun notifyReady(context: Context, confirm: Intent) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "به‌روزرسانی برنامه", NotificationManager.IMPORTANCE_LOW),
            )
        }
        confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val tap = PendingIntent.getActivity(
            context, 0, confirm, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(context, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(context)
        }
        builder
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("نسخه‌ی جدید جلسه‌نگار آماده است")
            .setContentText("برای نصب یک بار لمس کنید؛ جلسه‌ها و فایل‌های شما حفظ می‌شود.")
            .setContentIntent(tap)
            .setAutoCancel(true)
        manager.notify(NOTIFICATION_ID, builder.build())
    }
}

/** Receives the PackageInstaller outcome. */
class UpdateInstallReceiver : BroadcastReceiver() {
    @Suppress("DEPRECATION")
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val store = UpdateStore(context)
        val awaiting = store.awaiting()
        val pendingResult = goAsync()
        Thread {
            try {
                when (status) {
                    PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                        val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                        store.markNeededUserAction()
                        if (confirm != null) UpdateInstaller.notifyReady(context, confirm)
                        if (awaiting != null) UpdateReporter.send(context, awaiting.first, "pending_user_action")
                    }
                    // The process is replaced by the new build; its first launch reports "installed".
                    PackageInstaller.STATUS_SUCCESS -> Unit
                    else -> {
                        val code = UpdatePolicy.errorForInstallStatus(status)
                        if (code != UpdateError.INSTALL_BLOCKED) store.clearReady()
                        store.clearAwaiting()
                        if (awaiting != null) UpdateReporter.send(context, awaiting.first, "failed", code)
                    }
                }
            } finally {
                pendingResult.finish()
            }
        }.start()
    }
}
