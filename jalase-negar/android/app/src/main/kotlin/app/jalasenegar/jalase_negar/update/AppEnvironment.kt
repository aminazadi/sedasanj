package app.jalasenegar.jalase_negar.update

import android.content.Context
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import java.security.MessageDigest

/** Whether the app has an activity on screen; set by MainActivity, read by the worker. */
object AppState {
    @Volatile
    var inForeground = false
}

object AppEnvironment {
    @Suppress("DEPRECATION")
    fun versionCode(info: PackageInfo): Long =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) info.longVersionCode else info.versionCode.toLong()

    fun installedVersionCode(context: Context): Long =
        versionCode(context.packageManager.getPackageInfo(context.packageName, 0))

    @Suppress("DEPRECATION")
    fun installedCertSha256(context: Context): String? =
        certSha256(context.packageManager, context.packageName)

    /** SHA-256 of the public signing certificate of an installed package (never private material). */
    @Suppress("DEPRECATION")
    fun certSha256(pm: PackageManager, packageName: String): String? = try {
        val info = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            pm.getPackageInfo(packageName, PackageManager.GET_SIGNING_CERTIFICATES)
        } else {
            pm.getPackageInfo(packageName, PackageManager.GET_SIGNATURES)
        }
        fromPackageInfo(info)
    } catch (_: Exception) {
        null
    }

    /** Certificate of an APK file that is not installed yet. */
    @Suppress("DEPRECATION")
    fun archiveInfo(pm: PackageManager, path: String): PackageInfo? = try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            pm.getPackageArchiveInfo(path, PackageManager.GET_SIGNING_CERTIFICATES)
        } else {
            pm.getPackageArchiveInfo(path, PackageManager.GET_SIGNATURES)
        }
    } catch (_: Exception) {
        null
    }

    @Suppress("DEPRECATION")
    fun fromPackageInfo(info: PackageInfo?): String? {
        if (info == null) return null
        val signature: Signature? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            val signing = info.signingInfo ?: return null
            if (signing.hasMultipleSigners()) {
                signing.apkContentsSigners.firstOrNull()
            } else {
                // The newest certificate is the one the app is signed with now.
                signing.signingCertificateHistory.lastOrNull()
            }
        } else {
            info.signatures?.firstOrNull()
        }
        return signature?.let {
            MessageDigest.getInstance("SHA-256")
                .digest(it.toByteArray())
                .joinToString("") { byte -> "%02x".format(byte) }
        }
    }

    fun manufacturer(): String =
        Build.MANUFACTURER.lowercase().filter { it.isLetterOrDigit() || it in " ._-" }.take(32)
}
