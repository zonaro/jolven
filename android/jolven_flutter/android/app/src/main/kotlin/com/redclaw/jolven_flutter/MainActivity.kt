package com.redclaw.jolven_flutter

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.content.pm.ApplicationInfo
import java.util.Locale
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import org.json.JSONArray
import org.json.JSONObject

/**
 * Native bridge for a frontend only. Never reaches into private app directories,
 * launches bundled cores, injects input, or claims that an external game started.
 */
class MainActivity : FlutterActivity() {
    private val channelName = "jolven/external_emulators"
    private val selectRomRequest = 4083
    private var pendingImport: MethodChannel.Result? = null

    private data class Emulator(
        val id: String,
        val name: String,
        val packageName: String,
        val romLaunch: String = "manual"
    )

    // Known packages are queried explicitly in the manifest (no QUERY_ALL_PACKAGES).
    // VIEW URI entries are experimental until validated on physical devices.
    private val emulators = listOf(
        Emulator("retroarch64", "RetroArch 64", "com.retroarch.aarch64"),
        Emulator("retroarch32", "RetroArch 32", "com.retroarch.ra32"),
        Emulator("retroarch", "RetroArch", "com.retroarch"),
        Emulator("ppsspp", "PPSSPP", "org.ppsspp.ppsspp", "view_unverified"),
        Emulator("ppssppgold", "PPSSPP Gold", "org.ppsspp.ppssppgold", "view_unverified"),
        Emulator("dolphin", "Dolphin", "org.dolphinemu.dolphinemu", "view_unverified"),
        Emulator("mupen64", "Mupen64Plus FZ", "org.mupen64plusae.v3.fzurita"),
        Emulator("duckstation", "DuckStation", "org.duckstation.android"),
        Emulator("azahar", "Azahar", "org.azahar_emu.azahar")
    )

    private val prefs by lazy { getSharedPreferences("jolven_rom_catalog", MODE_PRIVATE) }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "listEmulators" -> result.success(emulators.map { e ->
                        mapOf(
                            "id" to e.id, "name" to e.name,
                            "packageName" to e.packageName,
                            "romLaunch" to e.romLaunch,
                            "installed" to isInstalled(e.packageName)
                        )
                    })
                    "listRoms" -> result.success(readRoms())
                    "listAndroidGames" -> result.success(listAndroidGames())
                    "openAndroidGame" -> result.success(
                        openAndroidGame(call.argument("packageName"))
                    )
                    "importRom" -> selectRom(result)
                    "removeRom" -> {
                        val uri = call.argument<String>("uri")
                        if (uri.isNullOrBlank()) {
                            result.error("INVALID_URI", "Missing catalog URI", null)
                        } else {
                            writeRoms(readRoms().filterNot { it["uri"] == uri })
                            result.success(null)
                        }
                    }
                    "openEmulator" -> {
                        result.success(openEmulator(call.argument("packageName")))
                    }
                    "launchRom" -> {
                        result.success(
                            launchRom(
                                call.argument("uri"),
                                call.argument("packageName")
                            )
                        )
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun listAndroidGames(): List<Map<String, String>> {
        // Android package visibility is intentionally limited to launchable apps.
        // Some games don't declare CATEGORY_GAME; this is a conservative list.
        val launchable = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return packageManager.queryIntentActivities(launchable, 0)
            .filter { resolved ->
                val info = resolved.activityInfo.applicationInfo
                info.category == ApplicationInfo.CATEGORY_GAME ||
                    (info.flags and ApplicationInfo.FLAG_IS_GAME) != 0
            }
            .distinctBy { it.activityInfo.packageName }
            .sortedBy { it.loadLabel(packageManager).toString().lowercase(Locale.getDefault()) }
            .map { resolved ->
                mapOf(
                    "packageName" to resolved.activityInfo.packageName,
                    "name" to resolved.loadLabel(packageManager).toString()
                )
            }
    }

    private fun openAndroidGame(packageName: String?): Map<String, String> {
        if (packageName.isNullOrBlank() ||
            listAndroidGames().none { it["packageName"] == packageName }) {
            return mapOf("status" to "missing")
        }
        return try {
            val launch = packageManager.getLaunchIntentForPackage(packageName)
                ?: return mapOf("status" to "missing")
            startActivity(launch)
            mapOf("status" to "game_opened")
        } catch (error: Exception) {
            mapOf("status" to "missing", "detail" to (error.message ?: ""))
        }
    }

    private fun isInstalled(packageName: String): Boolean = try {
        packageManager.getPackageInfo(packageName, 0)
        true
    } catch (_: Exception) {
        false
    }

    private fun readRoms(): List<Map<String, String>> {
        val data = try {
            JSONArray(prefs.getString("roms", "[]"))
        } catch (_: Exception) {
            JSONArray()
        }
        val result = mutableListOf<Map<String, String>>()
        for (index in 0 until data.length()) {
            val value = data.optJSONObject(index) ?: continue
            val uri = value.optString("uri")
            if (!uri.startsWith("content://")) continue
            val name = value.optString("name").ifBlank { "ROM" }
            result.add(mapOf("uri" to uri, "name" to name))
        }
        return result
    }

    private fun writeRoms(roms: List<Map<String, String>>) {
        val json = JSONArray()
        for (rom in roms) {
            json.put(JSONObject().put("uri", rom["uri"]).put("name", rom["name"]))
        }
        prefs.edit().putString("roms", json.toString()).apply()
    }

    private fun selectRom(result: MethodChannel.Result) {
        if (pendingImport != null) {
            result.error("BUSY", "Another file picker is already open", null)
            return
        }
        pendingImport = result
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or
                    Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            }
            startActivityForResult(intent, selectRomRequest)
        } catch (error: Exception) {
            pendingImport = null
            result.error("PICKER_UNAVAILABLE", error.message, null)
        }
    }

    @Deprecated("Using startActivityForResult for compatibility with FlutterActivity")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != selectRomRequest) return
        val result = pendingImport ?: return
        pendingImport = null
        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            result.success(null)
            return
        }
        try {
            if (uri.scheme != "content") {
                result.error("UNSUPPORTED_URI", "Only SAF document URIs are accepted", null)
                return
            }
            contentResolver.takePersistableUriPermission(
                uri, Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            val name = documentName(uri)
            val record = mapOf("uri" to uri.toString(), "name" to name)
            val previous = readRoms()
            if (previous.none { it["uri"] == uri.toString() }) {
                writeRoms(previous + record)
            }
            result.success(record)
        } catch (error: Exception) {
            result.error("URI_PERMISSION", error.message, null)
        }
    }

    private fun documentName(uri: Uri): String {
        return try {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    val column = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (column >= 0 && cursor.moveToFirst()) cursor.getString(column) else null
                }?.takeIf { it.isNotBlank() } ?: "ROM"
        } catch (_: Exception) {
            "ROM"
        }
    }

    private fun openEmulator(packageName: String?): Map<String, String> {
        val emulator = emulators.firstOrNull { it.packageName == packageName }
            ?: return mapOf("status" to "missing")
        if (!isInstalled(emulator.packageName)) return mapOf("status" to "missing")
        return try {
            val intent = packageManager.getLaunchIntentForPackage(emulator.packageName)
                ?: return mapOf("status" to "unsupported")
            startActivity(intent)
            mapOf("status" to "emulator_opened")
        } catch (error: Exception) {
            mapOf("status" to "unsupported", "detail" to (error.message ?: ""))
        }
    }

    private fun launchRom(uriText: String?, packageName: String?): Map<String, String> {
        val emulator = emulators.firstOrNull { it.packageName == packageName }
            ?: return mapOf("status" to "missing")
        if (!isInstalled(emulator.packageName)) return mapOf("status" to "missing")
        if (emulator.romLaunch != "view_unverified") {
            return mapOf("status" to "manual_only")
        }
        if (uriText == null || readRoms().none { it["uri"] == uriText }) {
            return mapOf("status" to "no_file_permission")
        }
        val uri = Uri.parse(uriText)
        try {
            contentResolver.openFileDescriptor(uri, "r")?.use { }
                ?: return mapOf("status" to "no_file_permission")
        } catch (_: Exception) {
            return mapOf("status" to "no_file_permission")
        }
        // A generic VIEW intent is experimental. An accepted intent is *not*
        // proof that the emulator opened the ROM or supports that file format.
        val intent = Intent(Intent.ACTION_VIEW).apply {
            data = uri
            setPackage(emulator.packageName)
            clipData = ClipData.newRawUri("rom", uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        return try {
            if (intent.resolveActivity(packageManager) == null) {
                mapOf("status" to "unsupported")
            } else {
                startActivity(intent)
                mapOf("status" to "handoff_requested_unverified")
            }
        } catch (error: Exception) {
            mapOf("status" to "unsupported", "detail" to (error.message ?: ""))
        }
    }

    override fun onDestroy() {
        pendingImport?.error("ACTIVITY_DESTROYED", "File selection cancelled", null)
        pendingImport = null
        super.onDestroy()
    }
}
