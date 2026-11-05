package app.jalasenegar.jalase_negar.update

import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

sealed class DownloadResult {
    object Ok : DownloadResult()
    object ChecksumMismatch : DownloadResult()
    data class Failed(val reason: String) : DownloadResult()
}

/**
 * Downloads one APK into the app's private directory, resuming a partial `.part` file with an
 * HTTP Range request. The finished file must match the announced size and SHA-256 or it is
 * deleted. Redirects are never followed, and only the fixed HTTPS origin is accepted.
 */
class ApkDownloader(
    private val origin: String = UPDATE_ORIGIN,
    private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
) {
    fun download(offer: UpdateOffer, target: File): DownloadResult {
        val url = offer.downloadUrl(origin)
        if (!url.startsWith("$origin/") || !(origin.startsWith("https://") || ALLOW_INSECURE_FOR_TESTS)) {
            return DownloadResult.Failed("origin_not_allowed")
        }
        target.parentFile?.mkdirs()
        val part = File(target.path + ".part")
        if (target.isFile) {
            if (verifies(target, offer)) return DownloadResult.Ok
            target.delete()
        }
        var attempt = 0
        while (attempt < 2) {
            attempt++
            val existing = if (part.isFile) part.length() else 0L
            if (existing > offer.size) part.delete()
            val result = fetch(url, offer, part)
            if (result == FETCH_RESTART) {
                part.delete()
                continue
            }
            if (result != FETCH_OK) return DownloadResult.Failed("network")
            break
        }
        if (!part.isFile || part.length() != offer.size) {
            // A short file keeps its bytes for the next resume; a long one is garbage.
            if (part.isFile && part.length() > offer.size) part.delete()
            return DownloadResult.Failed("incomplete")
        }
        if (sha256(part) != offer.sha256) {
            part.delete()
            return DownloadResult.ChecksumMismatch
        }
        if (!part.renameTo(target)) return DownloadResult.Failed("rename")
        return DownloadResult.Ok
    }

    private fun fetch(url: String, offer: UpdateOffer, part: File): Int {
        val existing = if (part.isFile) part.length() else 0L
        val connection = openConnection(URL(url))
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15_000
            connection.readTimeout = 30_000
            connection.setRequestProperty("Accept", "application/vnd.android.package-archive")
            if (existing in 1 until offer.size) {
                connection.setRequestProperty("Range", "bytes=$existing-")
                // The server serves a partial body only while the file is still this build.
                connection.setRequestProperty("If-Range", "\"${offer.sha256}\"")
            }
            val code = connection.responseCode
            return when {
                code == 416 -> if (existing == offer.size) FETCH_OK else FETCH_RESTART
                code == 206 && existing > 0 -> {
                    append(connection, part, append = true)
                    FETCH_OK
                }
                code == 200 -> {
                    append(connection, part, append = false)
                    FETCH_OK
                }
                else -> FETCH_FAILED
            }
        } catch (_: java.io.IOException) {
            return FETCH_FAILED
        } finally {
            connection.disconnect()
        }
    }

    private fun append(connection: HttpURLConnection, part: File, append: Boolean) {
        connection.inputStream.use { input ->
            FileOutputStream(part, append).use { output ->
                input.copyTo(output, 64 * 1024)
                output.fd.sync()
            }
        }
    }

    companion object {
        private const val FETCH_OK = 0
        private const val FETCH_RESTART = 1
        private const val FETCH_FAILED = 2

        /** Only unit tests talk to a local plain-HTTP server. */
        @Volatile
        var ALLOW_INSECURE_FOR_TESTS = false

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        fun verifies(file: File, offer: UpdateOffer): Boolean =
            file.isFile && file.length() == offer.size && sha256(file) == offer.sha256
    }
}
