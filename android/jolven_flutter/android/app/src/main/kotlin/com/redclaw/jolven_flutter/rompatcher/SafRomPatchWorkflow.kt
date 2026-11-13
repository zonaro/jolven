package com.redclaw.jolven_flutter.rompatcher

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files

/**
 * User-driven, offline patch flow. Source ROM and patch are copied into cache,
 * patched independently and then exported to a freshly selected SAF document.
 * On error the just-created output is deleted where the provider permits it.
 */
internal object SafRomPatchWorkflow {
    private const val MAX_ROM = 64L * 1024L * 1024L
    private const val MAX_PATCH = 8L * 1024L * 1024L
    private const val MAX_OUTPUT = 96L * 1024L * 1024L

    fun apply(
        resolver: ContentResolver,
        cacheDir: File,
        romUri: Uri,
        patchUri: Uri,
        destinationUri: Uri
    ): Map<String, String> {
        require(romUri.scheme == "content" && patchUri.scheme == "content")
        require(destinationUri.scheme == "content")
        require(destinationUri != romUri && destinationUri != patchUri) {
            "Output must be a new, separate document"
        }
        val source = Files.createTempFile(cacheDir.toPath(), "jolven-rom-", ".tmp")
        val patch = Files.createTempFile(cacheDir.toPath(), "jolven-patch-", ".tmp")
        val output = Files.createTempFile(cacheDir.toPath(), "jolven-output-", ".tmp")
        var exported = false
        try {
            copyBounded(resolver, romUri, source.toFile(), MAX_ROM)
            copyBounded(resolver, patchUri, patch.toFile(), MAX_PATCH)
            val inspection = RomPatchEngine.inspect(patch)
            require(inspection.format in setOf(PatchFormat.IPS, PatchFormat.UPS, PatchFormat.BPS)) {
                "Patch format recognized but no decoder is available"
            }
            // UPS/BPS include source/target checksums; require validation.
            RomPatchEngine.apply(
                source, patch, output,
                ApplyOptions(requireValidation = true)
            )
            require(Files.size(output) in 1..MAX_OUTPUT) { "Output exceeds size limit" }
            resolver.openOutputStream(destinationUri, "w")?.use { stream ->
                Files.newInputStream(output).use { input ->
                    input.copyTo(stream, bufferSize = 64 * 1024)
                }
            } ?: error("Cannot write destination document")
            exported = true
            return mapOf(
                "status" to "exported",
                "format" to inspection.format.name,
                "sha1" to RomPatchEngine.hashes(output).sha1
            )
        } catch (error: Exception) {
            if (!exported) {
                runCatching {
                    DocumentsContract.deleteDocument(resolver, destinationUri)
                }
            }
            throw error
        } finally {
            Files.deleteIfExists(source)
            Files.deleteIfExists(patch)
            Files.deleteIfExists(output)
        }
    }

    private fun copyBounded(
        resolver: ContentResolver, source: Uri, destination: File, limit: Long
    ) {
        val input = resolver.openInputStream(source) ?: error("Selected file is unreadable")
        var total = 0L
        input.use { reader ->
            FileOutputStream(destination).use { out ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val count = reader.read(buffer)
                    if (count < 0) break
                    total += count
                    require(total <= limit) { "Selected file exceeds size limit" }
                    out.write(buffer, 0, count)
                }
            }
        }
        require(total > 0) { "Empty file cannot be patched" }
    }
}
