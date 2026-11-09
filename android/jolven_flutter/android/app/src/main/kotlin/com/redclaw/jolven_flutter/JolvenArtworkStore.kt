package com.redclaw.jolven_flutter

import android.content.ContentResolver
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** Safe offline artwork: user-selected JPEG/PNG/WebP, never remote downloads. */
internal class JolvenArtworkStore(filesDir: File) {
    private val directory = File(filesDir, "artwork").also { it.mkdirs() }

    fun save(resolver: ContentResolver, input: Uri, romUri: String, kind: String): String {
        require(input.scheme == "content")
        require(kind == "cover" || kind == "label")
        require(romUri.startsWith("content://"))
        val temporary = File.createTempFile("artwork-", ".tmp", directory)
        try {
            val source = resolver.openInputStream(input) ?: error("Image is unavailable")
            var total = 0L
            source.use { stream ->
                FileOutputStream(temporary).use { output ->
                    val buffer = ByteArray(32 * 1024)
                    while (true) {
                        val size = stream.read(buffer)
                        if (size < 0) break
                        total += size
                        require(total <= MAX_BYTES) { "Image exceeds 8 MiB" }
                        output.write(buffer, 0, size)
                    }
                }
            }
            val ext = detectImageExtension(temporary)
                ?: error("Only JPEG, PNG and WebP files are supported")
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(temporary.path, options)
            require(options.outWidth in 1..MAX_DIMENSION && options.outHeight in 1..MAX_DIMENSION)
            require(options.outWidth.toLong() * options.outHeight <= MAX_PIXELS) {
                "Image dimensions are too large"
            }
            val hash = MessageDigest.getInstance("SHA-256")
                .digest(romUri.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
            val target = File(directory, "$hash-$kind.$ext")
            Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            return target.absolutePath
        } finally {
            temporary.delete()
        }
    }

    fun deleteIfOwned(path: String?) {
        if (path.isNullOrBlank()) return
        val file = File(path)
        if (file.canonicalFile.parentFile == directory.canonicalFile) file.delete()
    }

    private fun detectImageExtension(file: File): String? {
        val bytes = ByteArray(12)
        val count = FileInputStream(file).use { it.read(bytes) }
        if (count < 12) return null
        val png = byteArrayOf(0x89.toByte(), 0x50, 0x4e, 0x47)
        if (bytes.take(4).toByteArray().contentEquals(png)) return "png"
        if (bytes[0] == 0xff.toByte() && bytes[1] == 0xd8.toByte() &&
            bytes[2] == 0xff.toByte()) return "jpg"
        val riff = String(bytes, 0, 4, Charsets.US_ASCII) == "RIFF"
        val webp = String(bytes, 8, 4, Charsets.US_ASCII) == "WEBP"
        return if (riff && webp) "webp" else null
    }

    companion object {
        private const val MAX_BYTES = 8L * 1024L * 1024L
        private const val MAX_DIMENSION = 8192
        private const val MAX_PIXELS = 24L * 1024L * 1024L
    }
}
