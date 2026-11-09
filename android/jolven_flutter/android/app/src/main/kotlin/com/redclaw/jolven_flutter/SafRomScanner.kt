package com.redclaw.jolven_flutter

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract

/**
 * Bounded SAF enumeration; never follows filesystem symlinks or raw file paths.
 * The caller owns the user-granted tree URI. Run this on a background thread.
 */
internal object SafRomScanner {
    private const val MAX_DEPTH = 8
    private const val MAX_RESULTS = 2000
    private const val MAX_NODES = 6000

    private val extensions = setOf(
        "nes", "fds", "sfc", "smc", "fig", "gb", "gbc", "gba", "n64", "z64", "v64",
        "nds", "dsi", "3ds", "cci", "cxi", "gcm", "gcz", "rvz", "wbfs", "md", "smd",
        "gen", "sms", "gg", "ccd", "pbp", "chd", "bin", "cue", "img", "iso",
        "cso", "gdi", "pce", "a26", "a78", "zip", "7z", "d64", "t64", "prg"
    )

    fun scan(resolver: ContentResolver, treeUri: Uri): List<Map<String, String>> {
        require(treeUri.scheme == "content")
        val treeId = DocumentsContract.getTreeDocumentId(treeUri)
        val queue = ArrayDeque<Pair<String, Int>>()
        val visited = mutableSetOf<String>()
        val result = mutableListOf<Map<String, String>>()
        queue.add(treeId to 0)
        var seen = 0

        while (queue.isNotEmpty() && result.size < MAX_RESULTS && seen < MAX_NODES) {
            val (directoryId, depth) = queue.removeFirst()
            if (!visited.add(directoryId) || depth > MAX_DEPTH) continue
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, directoryId)
            val projection = arrayOf(
                DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                DocumentsContract.Document.COLUMN_MIME_TYPE
            )
            resolver.query(children, projection, null, null, null)?.use { cursor ->
                val idColumn = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
                val nameColumn = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
                val typeColumn = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_MIME_TYPE)
                if (idColumn < 0 || nameColumn < 0 || typeColumn < 0) return@use
                while (cursor.moveToNext() && seen < MAX_NODES && result.size < MAX_RESULTS) {
                    seen++
                    val id = cursor.getString(idColumn) ?: continue
                    val name = cursor.getString(nameColumn) ?: continue
                    val mimeType = cursor.getString(typeColumn) ?: continue
                    if (mimeType == DocumentsContract.Document.MIME_TYPE_DIR) {
                        if (depth < MAX_DEPTH) queue.add(id to (depth + 1))
                        continue
                    }
                    val extension = name.substringAfterLast('.', "").lowercase()
                    if (extension !in extensions) continue
                    val uri = DocumentsContract.buildDocumentUriUsingTree(treeUri, id)
                    result.add(mapOf("uri" to uri.toString(), "name" to name))
                }
            }
        }
        return result
    }
}
