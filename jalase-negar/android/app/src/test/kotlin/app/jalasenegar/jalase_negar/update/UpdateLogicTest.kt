package app.jalasenegar.jalase_negar.update

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.net.ServerSocket
import java.nio.file.Files
import java.security.MessageDigest

class UpdateLogicTest {
    private val cert = "a".repeat(64)

    private fun calm(
        recording: Boolean = false,
        chunks: Int = 0,
        text: Int = 0,
        foreground: Boolean = false,
        free: Long = 1000,
        apk: Long = 100,
        battery: Int = 80,
        charging: Boolean = false,
    ) = CalmGate.check(CalmInputs(recording, chunks, text, foreground, free, apk, battery, charging))

    // --- gating ---

    @Test fun calmWhenNothingIsRunning() = assertTrue(calm().calm)

    @Test fun recordingBlocks() = assertEquals("recording", calm(recording = true).reason)

    @Test fun unsentUploadsBlock() = assertEquals("upload_pending", calm(chunks = 2).reason)

    @Test fun pendingTextSyncBlocks() = assertEquals("text_sync_pending", calm(text = 1).reason)

    @Test fun foregroundBlocks() = assertEquals("foreground", calm(foreground = true).reason)

    @Test fun needsTwiceTheApkInFreeSpace() {
        assertFalse(calm(free = 199, apk = 100).calm)
        assertTrue(calm(free = 200, apk = 100).calm)
    }

    @Test fun lowBatteryBlocksUnlessCharging() {
        assertEquals("low_battery", calm(battery = 29).reason)
        assertTrue(calm(battery = 30).calm)
        assertTrue(calm(battery = 5, charging = true).calm)
    }

    // --- offers ---

    private fun offer(path: String = "/v1/jalase-negar/android/releases/3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77/download", sha: String = "f".repeat(64)) =
        UpdateOffer.parse("3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77", "1.2.0", 9L, 1024L, sha, 24, path, false)

    @Test fun validOfferIsAccepted() = assertNotNull(offer())

    @Test fun foreignOrEscapingPathsAreRejected() {
        assertNull(offer("https://evil.example/x.apk"))
        assertNull(offer("//evil.example/v1/jalase-negar/android/releases/a/download"))
        assertNull(offer("/v1/jalase-negar/android/releases/../../x"))
        assertNull(offer("/v1/jalase-negar/android/releases/a/download?x=1"))
        assertNull(offer("/other/path"))
    }

    @Test fun missingOrMalformedChecksumIsRejected() {
        assertNull(offer(sha = "zz"))
        assertNull(offer(sha = "F".repeat(63)))
    }

    // --- downgrade and signature ---

    @Test fun rejectsDowngradeEqualBuildForeignPackageAndForeignSigner() {
        val pkg = APP_PACKAGE
        assertNull(UpdatePolicy.archiveProblem(5, cert, pkg, 6, cert))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.archiveProblem(5, cert, pkg, 5, cert))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.archiveProblem(5, cert, pkg, 4, cert))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.archiveProblem(5, cert, "x.y", 6, cert))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.archiveProblem(5, cert, pkg, 6, "b".repeat(64)))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.archiveProblem(5, cert, pkg, 6, null))
    }

    @Test fun installFailureStatusesMapToCodes() {
        assertEquals(UpdateError.CHECKSUM_MISMATCH, UpdatePolicy.errorForInstallStatus(4))
        assertEquals(UpdateError.DOWNGRADE_REJECTED, UpdatePolicy.errorForInstallStatus(5))
        assertEquals(UpdateError.INSTALL_BLOCKED, UpdatePolicy.errorForInstallStatus(1))
        assertEquals(UpdateError.INSTALL_BLOCKED, UpdatePolicy.errorForInstallStatus(6))
    }

    // --- download: resume and checksum ---

    private lateinit var server: ServerSocket
    private lateinit var dir: File
    private val body = ByteArray(10_000) { (it * 31 % 251).toByte() }
    private val sha = MessageDigest.getInstance("SHA-256").digest(body).joinToString("") { "%02x".format(it) }
    private val rangeHeaders = mutableListOf<String?>()

    /** A tiny HTTP/1.1 server: 200 with the whole body, or 206 from the requested offset. */
    @Before fun start() {
        dir = Files.createTempDirectory("apk").toFile()
        ApkDownloader.ALLOW_INSECURE_FOR_TESTS = true
        server = ServerSocket(0, 5, java.net.InetAddress.getByName("127.0.0.1"))
        Thread {
            while (!server.isClosed) {
                try {
                    server.accept().use { socket ->
                        val reader = socket.getInputStream().bufferedReader()
                        var range: String? = null
                        while (true) {
                            val line = reader.readLine() ?: break
                            if (line.isEmpty()) break
                            if (line.startsWith("Range:", ignoreCase = true)) range = line.substringAfter(":").trim()
                        }
                        rangeHeaders += range
                        val out = socket.getOutputStream()
                        val from = range?.removePrefix("bytes=")?.removeSuffix("-")?.toInt() ?: 0
                        val data = body.copyOfRange(from, body.size)
                        val status = if (range != null) "206 Partial Content" else "200 OK"
                        out.write("HTTP/1.1 $status\r\nContent-Length: ${data.size}\r\nConnection: close\r\n\r\n".toByteArray())
                        out.write(data)
                        out.flush()
                    }
                } catch (_: java.io.IOException) {
                    // Server closed at the end of the test.
                }
            }
        }.also { it.isDaemon = true }.start()
    }

    @After fun stop() {
        server.close()
        ApkDownloader.ALLOW_INSECURE_FOR_TESTS = false
        dir.deleteRecursively()
    }

    private fun downloadOffer(shaValue: String = sha) = UpdateOffer(
        "3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77", "1.2.0", 9, body.size.toLong(), shaValue, 24,
        "/v1/jalase-negar/android/releases/3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a77/download", false,
    )

    private fun downloader() = ApkDownloader("http://127.0.0.1:${server.localPort}")

    @Test fun downloadsAndVerifiesTheChecksum() {
        val target = File(dir, "u.apk")
        assertEquals(DownloadResult.Ok, downloader().download(downloadOffer(), target))
        assertTrue(target.readBytes().contentEquals(body))
    }

    @Test fun resumesAPartialFileWithARangeRequest() {
        val target = File(dir, "u.apk")
        File(dir, "u.apk.part").writeBytes(body.copyOfRange(0, 4000))
        assertEquals(DownloadResult.Ok, downloader().download(downloadOffer(), target))
        assertEquals(listOf<String?>("bytes=4000-"), rangeHeaders)
        assertTrue(target.readBytes().contentEquals(body))
    }

    @Test fun aWrongChecksumDeletesTheFileAndIsReported() {
        val target = File(dir, "u.apk")
        val result = downloader().download(downloadOffer("0".repeat(64)), target)
        assertEquals(DownloadResult.ChecksumMismatch, result)
        assertFalse(target.exists())
        assertFalse(File(dir, "u.apk.part").exists())
    }

    @Test fun aCorruptResumeIsCaughtByTheChecksum() {
        val target = File(dir, "u.apk")
        File(dir, "u.apk.part").writeBytes(ByteArray(4000) { 1 })
        assertEquals(DownloadResult.ChecksumMismatch, downloader().download(downloadOffer(), target))
        assertFalse(target.exists())
    }

    @Test fun anInsecureOriginIsRefusedOutsideTests() {
        ApkDownloader.ALLOW_INSECURE_FOR_TESTS = false
        val result = downloader().download(downloadOffer(), File(dir, "u.apk"))
        assertEquals(DownloadResult.Failed("origin_not_allowed"), result)
        assertTrue(rangeHeaders.isEmpty())
    }
}
