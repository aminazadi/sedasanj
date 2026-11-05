package app.jalasenegar.jalase_negar.update

import java.net.URI

/** Error codes shared with the server (`update_*`) and the help center. */
object UpdateError {
    const val CHECKSUM_MISMATCH = "update_checksum_mismatch"
    const val DOWNGRADE_REJECTED = "update_downgrade_rejected"
    const val INSTALL_BLOCKED = "update_install_blocked"
}

/** The only origin the app ever asks for updates and downloads them from. */
const val UPDATE_ORIGIN = "https://api.sedasanj.ir"
const val DOWNLOAD_PREFIX = "/v1/jalase-negar/android/releases/"
const val APP_PACKAGE = "app.jalasenegar.jalase_negar"

/** An update the server offered, validated field by field. */
data class UpdateOffer(
    val id: String,
    val versionName: String,
    val versionCode: Long,
    val size: Long,
    val sha256: String,
    val minSdk: Int,
    val downloadPath: String,
    val mandatory: Boolean,
) {
    companion object {
        private val SHA256 = Regex("^[0-9a-f]{64}$")
        private val ID = Regex("^[0-9a-fA-F-]{8,64}$")

        /** Null when the offer is missing, incomplete or points anywhere but the fixed origin. */
        fun parse(
            id: String?,
            versionName: String?,
            versionCode: Long?,
            size: Long?,
            sha256: String?,
            minSdk: Int?,
            downloadPath: String?,
            mandatory: Boolean,
        ): UpdateOffer? {
            if (id == null || !ID.matches(id)) return null
            if (versionName.isNullOrBlank() || versionCode == null || versionCode < 1) return null
            if (size == null || size <= 0) return null
            val sha = sha256?.trim()?.lowercase() ?: return null
            if (!SHA256.matches(sha)) return null
            if (downloadPath == null || !isAllowedDownloadPath(downloadPath)) return null
            return UpdateOffer(id, versionName, versionCode, size, sha, minSdk ?: 0, downloadPath, mandatory)
        }

        /** Relative path under the release prefix; no scheme, host, query, escapes or backslashes. */
        fun isAllowedDownloadPath(path: String): Boolean {
            if (!path.startsWith(DOWNLOAD_PREFIX)) return false
            if (path.contains("..") || path.contains('\\') || path.contains('?') || path.contains('#')) {
                return false
            }
            return try {
                val uri = URI(path)
                uri.scheme == null && uri.authority == null
            } catch (_: Exception) {
                false
            }
        }
    }

    fun downloadUrl(origin: String = UPDATE_ORIGIN): String = origin + downloadPath
}

/** What decides whether a downloaded file may be installed over the running app. */
object UpdatePolicy {
    /**
     * Error code that forbids installing [archiveVersionCode] over [installedVersionCode], or null.
     * A downgrade or equal build, another package, or a different signing certificate are all refused.
     */
    fun archiveProblem(
        installedVersionCode: Long,
        installedCertSha256: String?,
        archivePackage: String?,
        archiveVersionCode: Long,
        archiveCertSha256: String?,
    ): String? {
        if (archivePackage != APP_PACKAGE) return UpdateError.DOWNGRADE_REJECTED
        if (archiveVersionCode <= installedVersionCode) return UpdateError.DOWNGRADE_REJECTED
        if (installedCertSha256 == null || archiveCertSha256 == null ||
            !installedCertSha256.equals(archiveCertSha256, ignoreCase = true)
        ) {
            return UpdateError.DOWNGRADE_REJECTED
        }
        return null
    }

    /** Maps a PackageInstaller failure status to the code reported to the server. */
    fun errorForInstallStatus(status: Int): String = when (status) {
        // STATUS_FAILURE_INVALID: the archive is corrupt or unparsable.
        4 -> UpdateError.CHECKSUM_MISMATCH
        // STATUS_FAILURE_CONFLICT / STATUS_FAILURE_INCOMPATIBLE: an older build or a foreign signature.
        5, 7 -> UpdateError.DOWNGRADE_REJECTED
        // BLOCKED, ABORTED, STORAGE and the generic failure: the phone refused to install.
        else -> UpdateError.INSTALL_BLOCKED
    }
}
