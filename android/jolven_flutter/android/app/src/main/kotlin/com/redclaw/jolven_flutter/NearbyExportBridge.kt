package com.redclaw.jolven_flutter

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.security.MessageDigest

/** Explicit SAF export of a TLS-pinned and SHA-256-verified Nearby download. */
internal class NearbyExportBridge(private val activity: Activity) {
    companion object {
        const val REQUEST_CODE = 4092
        private const val MAX_FILE = 8L * 1024L * 1024L * 1024L
    }

    private var pending: MethodChannel.Result? = null
    private var source: File? = null
    private var expectedHash: String? = null

    fun cacheDir(): String = activity.cacheDir.canonicalPath

    fun export(path: String?, name: String?, sha256: String?, result: MethodChannel.Result) {
        if (pending != null) {
            result.error("BUSY", "Another Nearby export is active", null)
            return
        }
        if (path.isNullOrBlank() || name.isNullOrBlank() ||
            name.length > 180 || name.startsWith(".") ||
            name.contains('/') || name.contains('\\') ||
            name.contains(':') || name.any { it.code < 32 } ||
            sha256 == null || !sha256.matches(Regex("[a-f0-9]{64}"))) {
            result.error("INVALID_EXPORT", "Invalid path, name or checksum", null)
            return
        }
        val file = try { File(path).canonicalFile } catch (_: Exception) { null }
        val cache = activity.cacheDir.canonicalFile
        if (file == null || !file.path.startsWith(cache.path + File.separator) ||
            file.isDirectory || !file.isFile || file.length() > MAX_FILE) {
            result.error("INVALID_SOURCE", "Only verified files in the app cache are accepted", null)
            return
        }
        pending = result
        source = file
        expectedHash = sha256
        try {
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/octet-stream"
                putExtra(Intent.EXTRA_TITLE, name)
                addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            }
            activity.startActivityForResult(intent, REQUEST_CODE)
        } catch (error: Exception) {
            pending = null
            source = null
            expectedHash = null
            result.error("PICKER_FAILED", error.message, null)
        }
    }

    fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != REQUEST_CODE) return false
        val response = pending ?: return true
        val localFile = source
        val checksum = expectedHash
        pending = null
        source = null
        expectedHash = null
        val target = data?.data
        if (resultCode != Activity.RESULT_OK || target == null) {
            response.success(mapOf("status" to "cancelled"))
            return true
        }
        if (localFile == null || checksum == null || target.scheme != "content") {
            response.error("INVALID_EXPORT", "Export session expired", null)
            return true
        }
        Thread({
            var success = false
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                var written = 0L
                val output = activity.contentResolver.openOutputStream(target, "w")
                    ?: error("Export destination unavailable")
                output.use { out ->
                    localFile.inputStream().use { input ->
                        val buffer = ByteArray(128 * 1024)
                        while (true) {
                            val size = input.read(buffer)
                            if (size < 0) break
                            written += size
                            require(written <= MAX_FILE && written <= localFile.length()) {
                                "File size changed"
                            }
                            digest.update(buffer, 0, size)
                            out.write(buffer, 0, size)
                        }
                    }
                }
                val actual = digest.digest().joinToString("") { "%02x".format(it) }
                require(actual == checksum && written == localFile.length()) {
                    "SHA-256 mismatch after export"
                }
                success = true
                activity.runOnUiThread {
                    response.success(mapOf("status" to "saved", "bytes" to written))
                }
            } catch (error: Exception) {
                if (!success) {
                    runCatching {
                        DocumentsContract.deleteDocument(activity.contentResolver, target)
                    }
                }
                activity.runOnUiThread {
                    response.error("EXPORT_FAILED", error.message, null)
                }
            }
        }, "jolven-nearby-export").apply { isDaemon = true }.start()
        return true
    }

    fun cancel() {
        pending?.error("ACTIVITY_DESTROYED", "Nearby export cancelled", null)
        pending = null
        source = null
        expectedHash = null
    }
}
