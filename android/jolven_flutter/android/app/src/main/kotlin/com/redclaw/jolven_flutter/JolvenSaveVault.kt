package com.redclaw.jolven_flutter

import android.content.Context
import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID

/**
 * Consent-based local save vault. Cannot read or write another emulator's
 * sandbox; the owner must explicitly export a save before importing it.
 */
internal class JolvenSaveVault(private val context: Context) {
    private val dir = File(context.filesDir, "save-vault").also { it.mkdirs() }
    private val prefs = context.getSharedPreferences("jolven_save_vault", Context.MODE_PRIVATE)

    private data class Entry(
        val id: String,
        val name: String,
        val romUri: String,
        val sha256: String,
        val sizeBytes: Long
    ) {
        fun asMap() = mapOf(
            "id" to id, "name" to name, "romUri" to romUri,
            "sha256" to sha256, "sizeBytes" to sizeBytes.toString()
        )
    }

    @Synchronized
    private fun entries(): List<Entry> {
        val data = try {
            JSONArray(prefs.getString("entries", "[]"))
        } catch (_: Exception) {
            JSONArray()
        }
        return (0 until data.length()).mapNotNull { idx ->
            val row = data.optJSONObject(idx) ?: return@mapNotNull null
            val id = row.optString("id")
            val name = row.optString("name")
            if (!id.matches(Regex("[0-9a-f-]{36}")) || name.isBlank()) return@mapNotNull null
            Entry(
                id, name, row.optString("romUri"), row.optString("sha256"),
                row.optLong("sizeBytes")
            )
        }
    }

    @Synchronized
    private fun write(entries: List<Entry>) {
        val array = JSONArray()
        for (entry in entries) {
            array.put(JSONObject().apply {
                for ((key, value) in entry.asMap()) put(key, value)
            })
        }
        prefs.edit().putString("entries", array.toString()).apply()
    }

    @Synchronized
    fun all(): List<Map<String, String>> = entries().filter {
        File(dir, it.id).isFile
    }.map { it.asMap() }

    @Synchronized
    fun import(resolver: ContentResolver, sourceUri: Uri, romUri: String?): Map<String, String> {
        require(sourceUri.scheme == "content") { "Select a save using the Android file picker" }
        val existing = entries()
        require(existing.size < MAX_ENTRIES) { "Save vault limit reached" }
        require(existing.sumOf { it.sizeBytes } < MAX_TOTAL_BYTES) { "Save vault is full" }
        val name = fileName(resolver, sourceUri).take(100)
        val id = UUID.randomUUID().toString()
        val destination = File(dir, id)
        var total = 0L
        val hash = MessageDigest.getInstance("SHA-256")
        try {
            val reader = resolver.openInputStream(sourceUri) ?: error("Selected save is unreadable")
            reader.use { input ->
                FileOutputStream(destination).use { output ->
                    val buffer = ByteArray(32 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        total += count
                        require(total <= MAX_FILE_BYTES) { "Save exceeds 32 MiB" }
                        require(total + existing.sumOf { it.sizeBytes } <= MAX_TOTAL_BYTES) {
                            "Save vault exceeds 128 MiB"
                        }
                        output.write(buffer, 0, count)
                        hash.update(buffer, 0, count)
                    }
                }
            }
            require(total > 0) { "Empty save file" }
            val digest = hash.digest().joinToString("") { "%02x".format(it) }
            val duplicate = existing.firstOrNull { it.sha256 == digest && it.sizeBytes == total }
            if (duplicate != null) {
                destination.delete()
                return duplicate.asMap()
            }
            val entry = Entry(id, name, romUri.orEmpty(), digest, total)
            write(existing + entry)
            return entry.asMap()
        } catch (error: Exception) {
            destination.delete()
            throw error
        }
    }

    @Synchronized
    fun export(resolver: ContentResolver, id: String, destinationUri: Uri): Map<String, String> {
        require(destinationUri.scheme == "content")
        val entry = entries().firstOrNull { it.id == id } ?: error("Save not found")
        val source = File(dir, entry.id)
        require(source.isFile)
        val actual = MessageDigest.getInstance("SHA-256")
        FileInputStream(source).use { stream ->
            val buffer = ByteArray(32 * 1024)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                actual.update(buffer, 0, count)
            }
        }
        val computed = actual.digest().joinToString("") { "%02x".format(it) }
        require(computed == entry.sha256) { "Save integrity check failed" }
        resolver.openOutputStream(destinationUri, "w")?.use { output ->
            FileInputStream(source).use { it.copyTo(output) }
        } ?: error("Destination is not writable")
        return mapOf("status" to "exported", "sha256" to computed)
    }

    @Synchronized
    fun displayName(id: String): String? = entries().firstOrNull { it.id == id }?.name

    @Synchronized
    fun delete(id: String): Boolean {
        val all = entries()
        if (all.none { it.id == id }) return false
        val file = File(dir, id)
        if (file.exists() && !file.delete()) return false
        write(all.filterNot { it.id == id })
        return true
    }

    private fun fileName(resolver: ContentResolver, uri: Uri): String {
        return try {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (column < 0 || !cursor.moveToFirst()) null
                    else cursor.getString(column)
                }?.takeIf { it.isNotBlank() } ?: "save.bin"
        } catch (_: Exception) {
            "save.bin"
        }
    }

    companion object {
        private const val MAX_FILE_BYTES = 32L * 1024L * 1024L
        private const val MAX_TOTAL_BYTES = 128L * 1024L * 1024L
        private const val MAX_ENTRIES = 250
    }
}
