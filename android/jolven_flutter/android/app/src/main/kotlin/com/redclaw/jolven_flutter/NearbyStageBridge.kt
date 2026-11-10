package com.redclaw.jolven_flutter

import android.app.Activity
import android.net.Uri
import android.provider.OpenableColumns
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.security.MessageDigest

/**
 * Copies a user-granted SAF file to temporary app cache for explicit Nearby upload.
 * Sources are not modified. The temporary copy is limited to 512 MiB.
 */
internal class NearbyStageBridge(private val activity: Activity) {
    private val maxBytes = 512L * 1024L * 1024L
    private val kinds = setOf("rom", "save", "cover", "label")

    fun stage(uriText: String?, kind: String?, result: MethodChannel.Result) {
        if (uriText.isNullOrBlank() || !uriText.startsWith("content://") ||
            kind == null || kind !in kinds) {
            result.error("INVALID_SOURCE", "Choose a personal file through SAF", null)
            return
        }
        val uri = Uri.parse(uriText)
        Thread({
            var staged: File? = null
            try {
                val name = documentName(uri)
                require(name.isNotBlank() && name.length <= 180 &&
                    !name.startsWith(".") && !name.endsWith(".") &&
                    name.trim() == name && !name.contains('/') &&
                    !name.contains('\\') && !name.contains(':') &&
                    name.none { it.code < 32 }) {
                    "Source document name is not safe for sharing"
                }
                val target = File.createTempFile("nearby-send-", ".bin", activity.cacheDir)
                staged = target
                val digest = MessageDigest.getInstance("SHA-256")
                var size = 0L
                val stream = activity.contentResolver.openInputStream(uri)
                    ?: error("Source could not be opened")
                stream.use { input ->
                    target.outputStream().use { output ->
                        val buffer = ByteArray(128 * 1024)
                        while (true) {
                            val read = input.read(buffer)
                            if (read < 0) break
                            size += read
                            require(size <= maxBytes) {
                                "Source exceeds the 512 MiB temporary staging limit"
                            }
                            digest.update(buffer, 0, read)
                            output.write(buffer, 0, read)
                        }
                    }
                }
                val hash = digest.digest().joinToString("") { "%02x".format(it) }
                val response = mapOf(
                    "path" to target.absolutePath,
                    "name" to name,
                    "kind" to kind,
                    "size" to size,
                    "sha256" to hash
                )
                activity.runOnUiThread { result.success(response) }
            } catch (error: Exception) {
                staged?.delete()
                activity.runOnUiThread {
                    result.error("STAGING_FAILED", error.message, null)
                }
            }
        }, "jolven-nearby-stage").apply { isDaemon = true }.start()
    }

    fun cleanup(path: String?): Boolean {
        if (path.isNullOrBlank()) return false
        val file = try { File(path).canonicalFile } catch (_: Exception) { return false }
        if (file.parentFile != activity.cacheDir.canonicalFile ||
            !file.name.startsWith("nearby-send-")) return false
        return file.delete()
    }

    private fun documentName(uri: Uri): String {
        return activity.contentResolver.query(
            uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null
        )?.use { cursor ->
            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
        } ?: error("Document name is unavailable")
    }
}
