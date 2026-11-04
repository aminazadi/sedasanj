package app.jalasenegar.jalase_negar

import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.security.MessageDigest

class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        // What the update check sends the server: SDK level, supported ABIs and the SHA-256 of
        // the public certificate the installed app is signed with (never any private material).
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, UPDATE_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method != "environment") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                val cert = signingCertSha256()
                if (cert == null) {
                    result.error("no_certificate", "signing certificate unavailable", null)
                } else {
                    result.success(
                        mapOf(
                            "sdkInt" to Build.VERSION.SDK_INT,
                            "abis" to Build.SUPPORTED_ABIS.toList(),
                            "certSha256" to cert,
                        ),
                    )
                }
            }
    }

    @Suppress("DEPRECATION")
    private fun signingCertSha256(): String? {
        return try {
            val signature: Signature? =
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                    val info = packageManager
                        .getPackageInfo(packageName, PackageManager.GET_SIGNING_CERTIFICATES)
                        .signingInfo
                    if (info == null) {
                        null
                    } else if (info.hasMultipleSigners()) {
                        info.apkContentsSigners.firstOrNull()
                    } else {
                        // The newest certificate is the one the installed app is signed with now.
                        info.signingCertificateHistory.lastOrNull()
                    }
                } else {
                    packageManager
                        .getPackageInfo(packageName, PackageManager.GET_SIGNATURES)
                        .signatures
                        ?.firstOrNull()
                }
            signature?.let {
                MessageDigest.getInstance("SHA-256")
                    .digest(it.toByteArray())
                    .joinToString("") { byte -> "%02x".format(byte) }
            }
        } catch (_: Exception) {
            null
        }
    }

    private companion object {
        const val UPDATE_CHANNEL = "app.jalasenegar.jalase_negar/update"
    }
}
