package com.redclaw.jolven_flutter

import android.net.Uri
import java.net.HttpURLConnection
import java.net.URL

/** Opt-in Libretro thumbnail lookup. Not a web scraper or bulk downloader. */
internal object LibretroThumbnailProvider {
    private val systems = mapOf(
        "nes" to "Nintendo - Nintendo Entertainment System",
        "snes" to "Nintendo - Super Nintendo Entertainment System",
        "gb" to "Nintendo - Game Boy",
        "gbc" to "Nintendo - Game Boy Color",
        "gba" to "Nintendo - Game Boy Advance",
        "n64" to "Nintendo - Nintendo 64",
        "nds" to "Nintendo - Nintendo DS",
        "genesis" to "Sega - Mega Drive - Genesis",
        "sms" to "Sega - Master System - Mark III",
        "gg" to "Sega - Game Gear",
        "ps1" to "Sony - PlayStation",
        "ps2" to "Sony - PlayStation 2",
        "psp" to "Sony - PlayStation Portable",
        "dreamcast" to "Sega - Dreamcast",
        "atari2600" to "Atari - 2600",
        "atari7800" to "Atari - 7800",
        "c64" to "Commodore - 64"
    )

    fun urlFor(platformId: String, title: String): String? {
        val system = systems[platformId] ?: return null
        if (title.isBlank() || title.length > 160) return null
        val normalized = title.trim().replace(
            Regex("[&*/:`<>?\\\\|\"]"), "_"
        )
        if (normalized.isBlank() || normalized == "." || normalized == "..") return null
        return Uri.Builder()
            .scheme("https")
            .authority("thumbnails.libretro.com")
            .appendPath(system)
            .appendPath("Named_Boxarts")
            .appendPath("$normalized.png")
            .build().toString()
    }

    data class Downloaded(val path: String, val source: String)

    fun download(
        store: JolvenArtworkStore, romUri: String,
        platformId: String, title: String,
    ): Downloaded {
        val uri = urlFor(platformId, title) ?: error("Unknown thumbnail system/title")
        val conn = URL(uri).openConnection() as HttpURLConnection
        conn.connectTimeout = 8000
        conn.readTimeout = 15000
        conn.instanceFollowRedirects = false
        conn.setRequestProperty("Accept", "image/png")
        conn.setRequestProperty("User-Agent", "Jolven-Android/0.1")
        try {
            if (conn.responseCode != HttpURLConnection.HTTP_OK) {
                error("Thumbnail not found or server unavailable")
            }
            if (conn.contentLengthLong > 8L * 1024L * 1024L) {
                error("Thumbnail exceeds size limit")
            }
            val path = conn.inputStream.use { store.saveStream(it, romUri, "cover") }
            return Downloaded(path, uri)
        } finally {
            conn.disconnect()
        }
    }
}
