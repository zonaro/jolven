package com.redclaw.jolven_flutter

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Offline-only collections. Stable references survive catalog reindexing. */
internal class JolvenCollections(context: Context) {
    private val prefs = context.getSharedPreferences("jolven_collections", Context.MODE_PRIVATE)

    private data class Entry(val id: String, val title: String, val refs: List<String>) {
        fun asMap() = mapOf("id" to id, "title" to title, "refs" to refs)
    }

    private fun read(): List<Entry> {
        val array = try {
            JSONArray(prefs.getString("collections", "[]"))
        } catch (_: Exception) {
            JSONArray()
        }
        val entries = mutableListOf<Entry>()
        for (index in 0 until array.length()) {
            val obj = array.optJSONObject(index) ?: continue
            val id = obj.optString("id")
            val title = obj.optString("title")
            if (id.isBlank() || title.isBlank()) continue
            val rawRefs = obj.optJSONArray("refs") ?: JSONArray()
            val refs = (0 until rawRefs.length()).mapNotNull { offset ->
                rawRefs.optString(offset).takeIf { isValidRef(it) }
            }.distinct().take(MAX_MEMBERS)
            entries.add(Entry(id, title, refs))
        }
        return entries.take(MAX_COLLECTIONS)
    }

    private fun save(entries: List<Entry>) {
        val data = JSONArray()
        for (entry in entries) {
            val item = JSONObject()
            item.put("id", entry.id)
            item.put("title", entry.title)
            item.put("refs", JSONArray(entry.refs))
            data.put(item)
        }
        prefs.edit().putString("collections", data.toString()).apply()
    }

    @Synchronized
    fun all(): List<Map<String, Any>> = read().map { it.asMap() }

    @Synchronized
    fun create(title: String): Map<String, Any>? {
        val clean = title.trim()
        if (clean.isBlank() || clean.length > MAX_TITLE) return null
        val old = read()
        if (old.size >= MAX_COLLECTIONS) return null
        val item = Entry(UUID.randomUUID().toString(), clean, emptyList())
        save(old + item)
        return item.asMap()
    }

    @Synchronized
    fun rename(id: String, title: String): Boolean {
        val clean = title.trim()
        if (clean.isBlank() || clean.length > MAX_TITLE) return false
        val old = read()
        if (old.none { it.id == id }) return false
        save(old.map { if (it.id == id) it.copy(title = clean) else it })
        return true
    }

    @Synchronized
    fun delete(id: String): Boolean {
        val old = read()
        if (old.none { it.id == id }) return false
        save(old.filterNot { it.id == id })
        return true
    }

    @Synchronized
    fun toggle(id: String, ref: String): Boolean? {
        if (!isValidRef(ref)) return null
        val old = read()
        val target = old.find { it.id == id } ?: return null
        val exists = ref in target.refs
        if (!exists && target.refs.size >= MAX_MEMBERS) return null
        val members = if (exists) target.refs - ref else target.refs + ref
        save(old.map { if (it.id == id) it.copy(refs = members) else it })
        return !exists
    }

    companion object {
        private const val MAX_TITLE = 72
        private const val MAX_COLLECTIONS = 100
        private const val MAX_MEMBERS = 2000

        private fun isValidRef(ref: String): Boolean =
            ref.length in 5..2048 &&
                (ref.startsWith("rom:content://") ||
                    ref.startsWith("android:") ||
                    ref.startsWith("remote:")) &&
                !ref.contains('\u0000')
    }
}
