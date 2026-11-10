package com.redclaw.jolven_flutter

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.content.pm.ApplicationInfo
import java.util.Locale
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.provider.DocumentsContract
import android.media.projection.MediaProjectionManager
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import com.redclaw.jolven_flutter.rompatcher.SafRomPatchWorkflow
import java.util.concurrent.Executors
import java.security.MessageDigest
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.common.EventChannel
import org.json.JSONArray
import org.json.JSONObject

/**
 * Native bridge for a frontend only. Never reaches into private app directories,
 * launches bundled cores, injects input, or claims that an external game started.
 */
class MainActivity : FlutterActivity() {
    private val channelName = "jolven/external_emulators"
    private var gamepadSink: EventChannel.EventSink? = null
    private var lastJoystickEventMs: Long = 0L
    private val selectRomRequest = 4083
    private val selectFolderRequest = 4084
    private val selectArtworkRequest = 4085
    private val pickPatchRequest = 4086
    private val savePatchRequest = 4087
    private val pickSaveRequest = 4088
    private val exportSaveRequest = 4089
    private val screenRecordRequest = 4090
    private val scanner = Executors.newSingleThreadExecutor()
    private var pendingImport: MethodChannel.Result? = null
    private var importMultiple = false
    private var artworkRomUri: String? = null
    private var artworkKind: String? = null
    private var patchRomUri: String? = null
    private var patchFileUri: String? = null
    private var saveRomUri: String? = null
    private var saveFileId: String? = null

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
        Emulator("ppsspp", "PPSSPP", "org.ppsspp.ppsspp", "view_documented"),
        Emulator("ppsspp-legacy", "PPSSPP Legacy", "org.ppsspp.ppsspplegacy", "view_documented"),
        Emulator("ppssppgold", "PPSSPP Gold", "org.ppsspp.ppssppgold", "view_documented"),
        Emulator("dolphin", "Dolphin", "org.dolphinemu.dolphinemu", "view_unverified"),
        Emulator("mupen64", "Mupen64Plus FZ", "org.mupen64plusae.v3.fzurita"),
        Emulator("duckstation", "DuckStation", "org.duckstation.android"),
        Emulator("azahar", "Azahar", "org.azahar_emu.azahar"),
        Emulator("drastic", "DraStic (external)", "com.dsemu.drastic")
    )

    private val prefs by lazy { getSharedPreferences("jolven_rom_catalog", MODE_PRIVATE) }
    private val collections by lazy { JolvenCollections(this) }
    private val artworkStore by lazy { JolvenArtworkStore(filesDir) }
    private val saveVault by lazy { JolvenSaveVault(this) }

    private data class RemoteClient(
        val id: String, val name: String, val packageName: String
    )
    // Adapted from Kwiq MoonlightIntegration's known apps; no access to private
    // host list, shortcut APIs or streaming credentials.
    private val remoteClients = listOf(
        RemoteClient("moonlight", "Moonlight", "com.limelight"),
        RemoteClient("moonlight-unofficial", "Moonlight (Unofficial)", "com.limelight.unofficial"),
        RemoteClient("moonlight-noir", "Moonlight Noir", "com.limelight.noir"),
        RemoteClient("steamlink", "Steam Link", "com.valvesoftware.steamlink"),
        RemoteClient("parsec", "Parsec", "tv.parsec.client"),
        RemoteClient("psremote", "PS Remote Play", "com.playstation.remoteplay"),
        RemoteClient("chiaki", "Chiaki", "com.metallic.chiaki"),
        RemoteClient("geforce", "GeForce NOW", "com.nvidia.geforcenow")
    )

    private fun manuallyIncludedAndroidGames(): Set<String> =
        prefs.getStringSet("manual_android_games", emptySet())?.toSet() ?: emptySet()


    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        EventChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "jolven/gamepad_diagnostics"
        ).setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                gamepadSink = events
            }
            override fun onCancel(arguments: Any?) {
                gamepadSink = null
            }
        })
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "listGamepads" -> result.success(listGamepads())
                    "openRetroArchGuide" -> result.success(openRetroArchGuide())
                    "listEmulators" -> result.success(emulators.map { e ->
                        mapOf(
                            "id" to e.id, "name" to e.name,
                            "packageName" to e.packageName,
                            "romLaunch" to e.romLaunch,
                            "installed" to isInstalled(e.packageName),
                            "versionName" to (emulatorVersion(e.packageName) ?: "")
                        )
                    })
                    "listRoms" -> result.success(readRoms())
                    "fingerprintRom" -> fingerprintRom(call.argument("uri"), result)
                    "listAndroidGames" -> result.success(listAndroidGames())
                    "listLaunchableApps" -> result.success(listLaunchableApps())
                    "addAndroidGame" -> {
                        val pkg = call.argument<String>("packageName")
                        result.success(addAndroidGame(pkg))
                    }
                    "listRemoteClients" -> result.success(remoteClients.map { client ->
                        mapOf(
                            "id" to client.id,
                            "name" to client.name,
                            "packageName" to client.packageName,
                            "installed" to isInstalled(client.packageName)
                        )
                    })
                    "openRemoteClient" -> result.success(
                        openRemoteClient(call.argument("packageName"))
                    )
                    "openAndroidGame" -> result.success(
                        openAndroidGame(call.argument("packageName"))
                    )
                    "importRom" -> selectRom(result)
                    "importRoms" -> selectRom(result, multiple = true)
                    "importFolder" -> selectFolder(result)
                    "pickArtwork" -> pickArtwork(
                        call.argument("uri"), call.argument("kind"), result
                    )
                    "clearArtwork" -> result.success(
                        clearArtwork(call.argument("uri"), call.argument("kind"))
                    )
                    "downloadLibretroCover" -> downloadLibretroCover(
                        call.argument("uri"),
                        call.argument("platformId"),
                        call.argument("title"),
                        call.argument<Boolean>("replaceExisting") == true,
                        result
                    )
                    "recordingStatus" -> result.success(mapOf(
                        "recording" to JolvenRecordingService.isRecording,
                        "error" to (JolvenRecordingService.lastError ?: ""),
                        "lastVideoUri" to (JolvenRecordingService.lastVideoUri ?: "")
                    ))
                    "startScreenRecording" -> requestScreenRecording(result)
                    "stopScreenRecording" -> {
                        JolvenRecordingService.stop(this)
                        result.success(mapOf("status" to "stop_requested"))
                    }
                    "listSavedFiles" -> result.success(saveVault.all())
                    "pickSaveFile" -> pickSaveFile(call.argument("romUri"), result)
                    "exportSaveFile" -> exportSaveFile(call.argument("id"), result)
                    "deleteSaveFile" -> result.success(
                        saveVault.delete(call.argument("id") ?: "")
                    )
                    "pickUserFile" -> pickPatchFile(result)
                    "hashUserFile" -> hashUserFile(call.argument("uri"), result)
                    "pickPatchFile" -> pickPatchFile(result)
                    "exportPatchedRom" -> exportPatchedRom(
                        call.argument("romUri"),
                        call.argument("patchUri"),
                        result
                    )
                    "updateRom" -> updateRom(call, result)
                    "listCollections" -> result.success(collections.all())
                    "createCollection" -> {
                        val name = call.argument<String>("title").orEmpty()
                        val created = collections.create(name)
                        if (created == null) result.error("INVALID_COLLECTION", "Invalid title or limit reached", null)
                        else result.success(created)
                    }
                    "renameCollection" -> result.success(
                        collections.rename(
                            call.argument<String>("id").orEmpty(),
                            call.argument<String>("title").orEmpty()
                        )
                    )
                    "deleteCollection" -> result.success(
                        collections.delete(call.argument<String>("id").orEmpty())
                    )
                    "toggleCollectionMember" -> {
                        val state = collections.toggle(
                            call.argument<String>("id").orEmpty(),
                            call.argument<String>("ref").orEmpty()
                        )
                        if (state == null) result.error("INVALID_MEMBER", "Invalid collection/member", null)
                        else result.success(state)
                    }
                    "removeRom" -> {
                        val uri = call.argument<String>("uri")
                        if (uri.isNullOrBlank()) {
                            result.error("INVALID_URI", "Missing catalog URI", null)
                        } else {
                            val entries = readRoms()
                            val removing = entries.filter { it["uri"] == uri }
                            writeRoms(entries.filterNot { it["uri"] == uri })
                            for (record in removing) {
                                artworkStore.deleteIfOwned(record["coverPath"])
                                artworkStore.deleteIfOwned(record["labelPath"])
                            }
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
                                call.argument("packageName"),
                                call.argument("retroCorePath"),
                                call.argument("retroRomPath")
                            )
                        )
                    }
                    else -> result.notImplemented()
                }
            }
    }

    private fun allLaunchable() =
        packageManager.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0
        ).distinctBy { it.activityInfo.packageName }

    private fun listLaunchableApps(): List<Map<String, String>> {
        val reserved = (emulators.map { it.packageName } +
            remoteClients.map { it.packageName } + packageName).toSet()
        return allLaunchable()
            .filter { it.activityInfo.packageName !in reserved }
            .sortedBy { it.loadLabel(packageManager).toString().lowercase(Locale.getDefault()) }
            .map { resolved -> mapOf(
                "packageName" to resolved.activityInfo.packageName,
                "name" to resolved.loadLabel(packageManager).toString()
            ) }
    }

    private fun listAndroidGames(): List<Map<String, String>> {
        val reserved = (emulators.map { it.packageName } +
            remoteClients.map { it.packageName } + packageName).toSet()
        val manual = manuallyIncludedAndroidGames()
        return allLaunchable()
            .filter { resolved ->
                val info = resolved.activityInfo.applicationInfo
                resolved.activityInfo.packageName !in reserved &&
                    (
                        resolved.activityInfo.packageName in manual ||
                        info.category == ApplicationInfo.CATEGORY_GAME ||
                        (info.flags and ApplicationInfo.FLAG_IS_GAME) != 0
                    )
            }
            .sortedBy { it.loadLabel(packageManager).toString().lowercase(Locale.getDefault()) }
            .map { resolved ->
                mapOf(
                    "packageName" to resolved.activityInfo.packageName,
                    "name" to resolved.loadLabel(packageManager).toString()
                )
            }
    }

    private fun addAndroidGame(packageName: String?): Map<String, String> {
        if (packageName.isNullOrBlank() ||
            listLaunchableApps().none { it["packageName"] == packageName }) {
            return mapOf("status" to "missing")
        }
        val changed = manuallyIncludedAndroidGames() + packageName
        prefs.edit().putStringSet("manual_android_games", changed).apply()
        return mapOf("status" to "added")
    }

    private fun openRemoteClient(packageName: String?): Map<String, String> {
        if (remoteClients.none { it.packageName == packageName }) {
            return mapOf("status" to "missing")
        }
        if (packageName == null || !isInstalled(packageName)) {
            return mapOf("status" to "missing")
        }
        return try {
            val intent = packageManager.getLaunchIntentForPackage(packageName)
                ?: return mapOf("status" to "unsupported")
            startActivity(intent)
            mapOf("status" to "client_opened")
        } catch (error: Exception) {
            mapOf("status" to "unsupported", "detail" to (error.message ?: ""))
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

    private fun emulatorVersion(packageName: String): String? = try {
        packageManager.getPackageInfo(packageName, 0).versionName
    } catch (_: Exception) {
        null
    }

    private fun listGamepads(): List<Map<String, String>> {
        val manager = getSystemService(android.hardware.input.InputManager::class.java)
            ?: return emptyList()
        return manager.inputDeviceIds.toList().mapNotNull { id -> manager.getInputDevice(id) }
            .filter { device ->
                (device.sources and InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD ||
                    (device.sources and InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK ||
                    (device.sources and InputDevice.SOURCE_DPAD) == InputDevice.SOURCE_DPAD
            }
            .distinctBy { it.id }
            .map { device ->
                mapOf("id" to device.id.toString(), "name" to device.name)
            }
    }

    private fun openRetroArchGuide(): Map<String, String> {
        val link = Uri.parse("https://docs.libretro.com/guides/install-android/")
        return try {
            startActivity(Intent(Intent.ACTION_VIEW, link))
            mapOf("status" to "guide_requested")
        } catch (error: Exception) {
            mapOf("status" to "unsupported", "detail" to (error.message ?: ""))
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
            result.add(
                mapOf(
                    "uri" to uri,
                    "name" to value.optString("name").ifBlank { "ROM" },
                    "platformId" to value.optString("platformId"),
                    "emulatorPackage" to value.optString("emulatorPackage"),
                    "favorite" to value.optString("favorite", "false"),
                    "coverPath" to value.optString("coverPath"),
                    "coverSource" to value.optString("coverSource"),
                    "labelPath" to value.optString("labelPath"),
                    "retroCorePath" to value.optString("retroCorePath"),
                    "retroRomPath" to value.optString("retroRomPath"),
                    "sha256" to value.optString("sha256"),
                    "sizeBytes" to value.optString("sizeBytes")
                )
            )
        }
        return result
    }

    private fun fingerprintRom(uriText: String?, result: MethodChannel.Result) {
        val known = readRoms().any { it["uri"] == uriText }
        if (uriText.isNullOrBlank() || !known) {
            result.error("ROM_NOT_FOUND", "ROM not in local catalog", null)
            return
        }
        val uri = Uri.parse(uriText)
        scanner.execute {
            try {
                val input = contentResolver.openInputStream(uri)
                    ?: error("Document is no longer available")
                val digest = input.use { RomFingerprint.digest(it) }
                runOnUiThread {
                    // Refresh the current record; never overwrite user edits
                    // made to favorites, platform or artwork during hashing.
                    val entries = readRoms()
                    if (entries.none { it["uri"] == uriText }) {
                        result.error("ROM_REMOVED", "ROM no longer in catalog", null)
                    } else {
                        writeRoms(entries.map { record ->
                            if (record["uri"] != uriText) record
                            else record + mapOf(
                                "sha256" to digest.sha256,
                                "sizeBytes" to digest.size.toString()
                            )
                        })
                        result.success(mapOf(
                            "sha256" to digest.sha256,
                            "sizeBytes" to digest.size.toString()
                        ))
                    }
                }
            } catch (_: Exception) {
                runOnUiThread {
                    result.error(
                        "FINGERPRINT_FAILED",
                        "ROM unreadable, permission revoked or exceeds 512 MiB",
                        null
                    )
                }
            }
        }
    }

    private fun writeRoms(roms: List<Map<String, String>>) {
        val json = JSONArray()
        for (rom in roms) {
            val record = JSONObject()
            for ((key, value) in rom) record.put(key, value)
            json.put(record)
        }
        prefs.edit().putString("roms", json.toString()).apply()
    }

    @Synchronized
    private fun mergeRoms(selected: List<Map<String, String>>): List<Map<String, String>> {
        val old = readRoms()
        val existing = old.mapNotNull { it["uri"] }.toMutableSet()
        val added = selected.filter { row ->
            val uri = row["uri"] ?: return@filter false
            uri.startsWith("content://") && existing.add(uri)
        }
        if (added.isNotEmpty()) writeRoms(old + added)
        return added
    }

    private fun updateRom(call: io.flutter.plugin.common.MethodCall, result: MethodChannel.Result) {
        val uri = call.argument<String>("uri")
        if (uri.isNullOrBlank()) {
            result.error("INVALID_URI", "ROM URI is missing", null)
            return
        }
        val old = readRoms()
        if (old.none { it["uri"] == uri }) {
            result.error("NOT_FOUND", "ROM is no longer in the catalog", null)
            return
        }
        val platform = call.argument<String>("platformId")
        val emulator = call.argument<String>("emulatorPackage")
        val favorite = call.argument<Boolean>("favorite")
        val retroCore = call.argument<String>("retroCorePath")
        val retroRom = call.argument<String>("retroRomPath")
        if (retroCore != null && retroCore.isNotBlank() &&
            !validAbsolutePath(retroCore, true)) {
            result.error("INVALID_CORE_PATH", "Expected absolute .so core path", null)
            return
        }
        if (retroRom != null && retroRom.isNotBlank() &&
            !validAbsolutePath(retroRom, false)) {
            result.error("INVALID_ROM_PATH", "Expected absolute ROM path", null)
            return
        }
        if (platform != null && !platform.matches(Regex("[a-z0-9_-]{1,32}"))) {
            result.error("INVALID_PLATFORM", "Invalid platform ID", null)
            return
        }
        if (emulator != null && emulators.none { it.packageName == emulator }) {
            result.error("INVALID_EMULATOR", "Unknown emulator package", null)
            return
        }
        val updated = old.map { rom ->
            if (rom["uri"] != uri) rom else {
                rom.toMutableMap().apply {
                    if (platform != null) put("platformId", platform)
                    if (emulator != null) put("emulatorPackage", emulator)
                    if (favorite != null) put("favorite", favorite.toString())
                    if (retroCore != null) put("retroCorePath", retroCore)
                    if (retroRom != null) put("retroRomPath", retroRom)
                }
            }
        }
        writeRoms(updated)
        result.success(null)
    }

    private fun selectRom(result: MethodChannel.Result, multiple: Boolean = false) {
        if (pendingImport != null) {
            result.error("BUSY", "Another file picker is already open", null)
            return
        }
        pendingImport = result
        importMultiple = multiple
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, multiple)
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
            }
            startActivityForResult(intent, selectRomRequest)
        } catch (error: Exception) {
            pendingImport = null
            result.error("PICKER_UNAVAILABLE", error.message, null)
        }
    }

    private fun selectFolder(result: MethodChannel.Result) {
        if (pendingImport != null) {
            result.error("BUSY", "Another file picker is already open", null)
            return
        }
        pendingImport = result
        importMultiple = true
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
            }
            startActivityForResult(intent, selectFolderRequest)
        } catch (error: Exception) {
            pendingImport = null
            result.error("PICKER_UNAVAILABLE", error.message, null)
        }
    }

    private fun requestScreenRecording(result: MethodChannel.Result) {
        if (android.os.Build.VERSION.SDK_INT < 29) {
            result.error("UNSUPPORTED_ANDROID", "Screen recording requires Android 10+", null)
            return
        }
        if (JolvenRecordingService.isRecording) {
            result.success(mapOf("status" to "already_recording"))
            return
        }
        if (pendingImport != null) {
            result.error("BUSY", "Another picker or permission request is open", null)
            return
        }
        pendingImport = result
        try {
            val manager = getSystemService(MediaProjectionManager::class.java)
            startActivityForResult(manager.createScreenCaptureIntent(), screenRecordRequest)
        } catch (error: Exception) {
            pendingImport = null
            result.error("CAPTURE_PERMISSION", error.message, null)
        }
    }

    private fun hashUserFile(uriText: String?, result: MethodChannel.Result) {
        if (uriText.isNullOrBlank() || !uriText.startsWith("content://")) {
            result.error("INVALID_FILE", "Select file via SAF", null)
            return
        }
        scanner.execute {
            try {
                val uri = Uri.parse(uriText)
                val digest = MessageDigest.getInstance("SHA-256")
                var size = 0L
                val stream = contentResolver.openInputStream(uri)
                    ?: error("File cannot be read")
                stream.use { input ->
                    val buffer = ByteArray(32 * 1024)
                    while (true) {
                        val length = input.read(buffer)
                        if (length < 0) break
                        size += length
                        require(size <= 64L * 1024L * 1024L) {
                            "File exceeds 64 MiB inspection limit"
                        }
                        digest.update(buffer, 0, length)
                    }
                }
                val checksum = digest.digest().joinToString("") {
                    "%02x".format(it)
                }
                runOnUiThread {
                    result.success(mapOf("sha256" to checksum, "sizeBytes" to size.toString()))
                }
            } catch (error: Exception) {
                runOnUiThread { result.error("HASH_FAILED", error.message, null) }
            }
        }
    }

    private fun pickSaveFile(romUri: String?, result: MethodChannel.Result) {
        if (pendingImport != null) {
            result.error("BUSY", "A file picker is already open", null)
            return
        }
        if (!romUri.isNullOrBlank() &&
            readRoms().none { it["uri"] == romUri }) {
            result.error("INVALID_ROM", "Unknown ROM reference", null)
            return
        }
        pendingImport = result
        saveRomUri = romUri
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
            }
            startActivityForResult(intent, pickSaveRequest)
        } catch (error: Exception) {
            pendingImport = null
            saveRomUri = null
            result.error("SAVE_PICKER", error.message, null)
        }
    }

    private fun exportSaveFile(id: String?, result: MethodChannel.Result) {
        if (pendingImport != null) {
            result.error("BUSY", "A file picker is already open", null)
            return
        }
        val name = id?.let { saveVault.displayName(it) } ?: run {
            result.error("SAVE_NOT_FOUND", "Save no longer exists", null)
            return
        }
        pendingImport = result
        saveFileId = id
        try {
            val safeName = name.replace(Regex("[^a-zA-Z0-9._ ()-]"), "_")
                .take(95).ifBlank { "save.bin" }
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/octet-stream"
                putExtra(Intent.EXTRA_TITLE, safeName)
            }
            startActivityForResult(intent, exportSaveRequest)
        } catch (error: Exception) {
            pendingImport = null
            saveFileId = null
            result.error("SAVE_DESTINATION", error.message, null)
        }
    }

    private fun pickPatchFile(result: MethodChannel.Result) {
        if (pendingImport != null) {
            result.error("BUSY", "A file picker is already open", null)
            return
        }
        pendingImport = result
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "*/*"
                addFlags(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                )
            }
            startActivityForResult(intent, pickPatchRequest)
        } catch (error: Exception) {
            pendingImport = null
            result.error("PATCH_PICKER", error.message, null)
        }
    }

    private fun exportPatchedRom(
        romUri: String?, patchUri: String?, result: MethodChannel.Result
    ) {
        if (pendingImport != null) {
            result.error("BUSY", "A file picker is already open", null)
            return
        }
        val rom = readRoms().firstOrNull { it["uri"] == romUri }
        if (rom == null || patchUri.isNullOrBlank() || !patchUri.startsWith("content://")) {
            result.error("PATCH_INPUT", "Select a library ROM and a patch document", null)
            return
        }
        patchRomUri = romUri
        patchFileUri = patchUri
        pendingImport = result
        val baseName = rom["name"].orEmpty()
            .replace(Regex("[^a-zA-Z0-9._ ()-]"), "_")
            .take(90)
            .ifBlank { "rom.bin" }
        val stem = baseName.substringBeforeLast('.', baseName)
        val ext = baseName.substringAfterLast('.', "bin")
        try {
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/octet-stream"
                putExtra(Intent.EXTRA_TITLE, "$stem (patched).$ext")
            }
            startActivityForResult(intent, savePatchRequest)
        } catch (error: Exception) {
            pendingImport = null
            patchRomUri = null
            patchFileUri = null
            result.error("PATCH_DESTINATION", error.message, null)
        }
    }

    private fun pickArtwork(
        romUri: String?, kind: String?, result: MethodChannel.Result
    ) {
        if (pendingImport != null) {
            result.error("BUSY", "File picker is open", null)
            return
        }
        if (romUri.isNullOrBlank() || readRoms().none { it["uri"] == romUri } ||
            (kind != "cover" && kind != "label")) {
            result.error("INVALID_ARTWORK", "ROM or artwork kind is invalid", null)
            return
        }
        pendingImport = result
        artworkRomUri = romUri
        artworkKind = kind
        try {
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivityForResult(intent, selectArtworkRequest)
        } catch (error: Exception) {
            pendingImport = null
            artworkRomUri = null
            artworkKind = null
            result.error("IMAGE_PICKER", error.message, null)
        }
    }

    private fun downloadLibretroCover(
        romUri: String?, platformId: String?, title: String?,
        replaceExisting: Boolean, result: MethodChannel.Result
    ) {
        if (romUri.isNullOrBlank() || platformId.isNullOrBlank() ||
            title.isNullOrBlank()) {
            result.error("INVALID_THUMBNAIL", "Missing ROM/system/title", null)
            return
        }
        val current = readRoms().firstOrNull { it["uri"] == romUri }
        if (current == null) {
            result.error("ROM_NOT_FOUND", "ROM not in catalog", null)
            return
        }
        if (!replaceExisting && current["coverPath"].orEmpty().isNotBlank()) {
            result.error("COVER_EXISTS", "Cover already set", null)
            return
        }
        if (LibretroThumbnailProvider.urlFor(platformId, title) == null) {
            result.error("UNSUPPORTED_THUMBNAIL", "Unsupported console/title", null)
            return
        }
        scanner.execute {
            try {
                val downloaded = LibretroThumbnailProvider.download(
                    artworkStore, romUri, platformId, title
                )
                runOnUiThread {
                    val records = readRoms()
                    val old = records.firstOrNull { it["uri"] == romUri }
                    if (old == null) {
                        artworkStore.deleteIfOwned(downloaded.path)
                        result.error("ROM_REMOVED", "ROM removed during download", null)
                    } else {
                        writeRoms(records.map { record ->
                            if (record["uri"] != romUri) record
                            else record + mapOf(
                                "coverPath" to downloaded.path,
                                "coverSource" to downloaded.source
                            )
                        })
                        if (old["coverPath"] != downloaded.path) {
                            artworkStore.deleteIfOwned(old["coverPath"])
                        }
                        result.success(mapOf(
                            "path" to downloaded.path,
                            "source" to downloaded.source
                        ))
                    }
                }
            } catch (_: Exception) {
                runOnUiThread {
                    result.error(
                        "THUMBNAIL_FAILED",
                        "Thumbnail not found or network unavailable", null
                    )
                }
            }
        }
    }

    private fun clearArtwork(romUri: String?, kind: String?): Boolean {
        if (romUri.isNullOrBlank() || (kind != "cover" && kind != "label")) return false
        val key = if (kind == "cover") "coverPath" else "labelPath"
        val entries = readRoms()
        val target = entries.firstOrNull { it["uri"] == romUri } ?: return false
        writeRoms(entries.map { record ->
            if (record["uri"] != romUri) record
            else if (kind == "cover") record + mapOf(
                "coverPath" to "", "coverSource" to ""
            )
            else record + (key to "")
        })
        artworkStore.deleteIfOwned(target[key])
        return true
    }

    @Deprecated("Using startActivityForResult for compatibility with FlutterActivity")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != selectRomRequest &&
            requestCode != selectFolderRequest &&
            requestCode != selectArtworkRequest &&
            requestCode != pickPatchRequest &&
            requestCode != savePatchRequest &&
            requestCode != pickSaveRequest &&
            requestCode != exportSaveRequest &&
            requestCode != screenRecordRequest) return
        val result = pendingImport ?: return
        pendingImport = null
        val multiple = importMultiple
        importMultiple = false

        if (requestCode == screenRecordRequest) {
            if (resultCode != Activity.RESULT_OK || data == null) {
                result.success(mapOf("status" to "cancelled"))
                return
            }
            try {
                JolvenRecordingService.start(this, resultCode, data)
                result.success(mapOf("status" to "consent_received"))
            } catch (error: Exception) {
                result.error("CAPTURE_START", error.message, null)
            }
            return
        }

        if (requestCode == pickSaveRequest) {
            val associatedRom = saveRomUri
            saveRomUri = null
            val selected = data?.data
            if (resultCode != Activity.RESULT_OK || selected?.scheme != "content") {
                result.success(null)
                return
            }
            try {
                contentResolver.takePersistableUriPermission(
                    selected, Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
            } catch (error: Exception) {
                result.error("SAVE_PERMISSION", error.message, null)
                return
            }
            scanner.execute {
                try {
                    val entry = saveVault.import(contentResolver, selected, associatedRom)
                    runOnUiThread { result.success(entry) }
                } catch (error: Exception) {
                    runOnUiThread { result.error("SAVE_IMPORT", error.message, null) }
                }
            }
            return
        }

        if (requestCode == exportSaveRequest) {
            val id = saveFileId
            saveFileId = null
            val destination = data?.data
            if (resultCode != Activity.RESULT_OK || destination == null) {
                result.success(mapOf("status" to "cancelled"))
                return
            }
            if (id == null) {
                result.error("SAVE_NOT_FOUND", "Save selection expired", null)
                return
            }
            scanner.execute {
                try {
                    val report = saveVault.export(contentResolver, id, destination)
                    runOnUiThread { result.success(report) }
                } catch (error: Exception) {
                    runCatching {
                        DocumentsContract.deleteDocument(contentResolver, destination)
                    }
                    runOnUiThread { result.error("SAVE_EXPORT", error.message, null) }
                }
            }
            return
        }

        if (requestCode == pickPatchRequest) {
            val selected = data?.data
            if (resultCode != Activity.RESULT_OK || selected?.scheme != "content") {
                result.success(null)
                return
            }
            try {
                contentResolver.takePersistableUriPermission(
                    selected, Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
                result.success(selected.toString())
            } catch (error: Exception) {
                result.error("PATCH_READ", error.message, null)
            }
            return
        }
        if (requestCode == savePatchRequest) {
            val rom = patchRomUri
            val patch = patchFileUri
            val target = data?.data
            patchRomUri = null
            patchFileUri = null
            if (resultCode != Activity.RESULT_OK || target == null) {
                result.success(mapOf("status" to "cancelled"))
                return
            }
            if (rom == null || patch == null) {
                result.error("PATCH_INPUT", "Missing patch source", null)
                return
            }
            scanner.execute {
                try {
                    val report = SafRomPatchWorkflow.apply(
                        contentResolver, cacheDir, Uri.parse(rom),
                        Uri.parse(patch), target
                    )
                    runOnUiThread { result.success(report) }
                } catch (error: Exception) {
                    runOnUiThread {
                        result.error("PATCH_FAILED", error.message, null)
                    }
                }
            }
            return
        }

        if (requestCode == selectArtworkRequest) {
            val romUri = artworkRomUri
            val kind = artworkKind
            artworkRomUri = null
            artworkKind = null
            val selectedImage = data?.data
            if (resultCode != Activity.RESULT_OK || selectedImage == null) {
                result.success(null)
                return
            }
            if (romUri.isNullOrBlank() || kind.isNullOrBlank()) {
                result.error("INVALID_ARTWORK", "Selection expired", null)
                return
            }
            scanner.execute {
                try {
                    val saved = artworkStore.save(contentResolver, selectedImage, romUri, kind)
                    val key = if (kind == "cover") "coverPath" else "labelPath"
                    val entries = readRoms()
                    val previous = entries.firstOrNull { it["uri"] == romUri }
                    if (previous == null) {
                        artworkStore.deleteIfOwned(saved)
                        runOnUiThread {
                            result.error("ROM_REMOVED", "ROM was removed during selection", null)
                        }
                    } else {
                        writeRoms(entries.map { record ->
                            if (record["uri"] != romUri) record
                            else if (kind == "cover") record + mapOf(
                                "coverPath" to saved, "coverSource" to ""
                            )
                            else record + (key to saved)
                        })
                        if (previous[key] != saved) artworkStore.deleteIfOwned(previous[key])
                        runOnUiThread { result.success(saved) }
                    }
                } catch (error: Exception) {
                    runOnUiThread { result.error("ARTWORK_FAILED", error.message, null) }
                }
            }
            return
        }

        if (resultCode != Activity.RESULT_OK || data == null) {
            result.success(if (multiple) emptyList<Map<String, String>>() else null)
            return
        }

        if (requestCode == selectFolderRequest) {
            val treeUri = data.data
            if (treeUri == null || treeUri.scheme != "content") {
                result.error("INVALID_FOLDER", "No valid SAF tree was selected", null)
                return
            }
            try {
                contentResolver.takePersistableUriPermission(
                    treeUri, Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
            } catch (error: Exception) {
                result.error("URI_PERMISSION", error.message, null)
                return
            }
            scanner.execute {
                try {
                    val selected = SafRomScanner.scan(contentResolver, treeUri)
                    val added = mergeRoms(selected)
                    runOnUiThread { result.success(added) }
                } catch (error: Exception) {
                    runOnUiThread {
                        result.error("FOLDER_SCAN_FAILED", error.message, null)
                    }
                }
            }
            return
        }

        val picked = mutableListOf<Uri>()
        data.data?.let(picked::add)
        data.clipData?.let { clip ->
            for (index in 0 until clip.itemCount.coerceAtMost(250)) {
                clip.getItemAt(index).uri?.let(picked::add)
            }
        }
        val imported = mutableListOf<Map<String, String>>()
        for (uri in picked.distinctBy { it.toString() }.take(250)) {
            if (uri.scheme != "content") continue
            try {
                contentResolver.takePersistableUriPermission(
                    uri, Intent.FLAG_GRANT_READ_URI_PERMISSION
                )
                imported.add(mapOf("uri" to uri.toString(), "name" to documentName(uri)))
            } catch (_: Exception) {
                // Skip documents whose grant was revoked or can't persist.
            }
        }
        val added = mergeRoms(imported)
        result.success(if (multiple) added else added.firstOrNull())
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

    private fun validAbsolutePath(value: String, core: Boolean): Boolean {
        if (value.length !in 2..2048 || !value.startsWith("/")) return false
        if (value.any { it == '\u0000' || it == '\n' || it == '\r' }) return false
        return !core || value.endsWith(".so")
    }

    private fun launchRom(
        uriText: String?, packageName: String?,
        retroCorePath: String? = null, retroRomPath: String? = null
    ): Map<String, String> {
        val emulator = emulators.firstOrNull { it.packageName == packageName }
            ?: return mapOf("status" to "missing")
        if (!isInstalled(emulator.packageName)) return mapOf("status" to "missing")
        if (emulator.id.startsWith("retroarch")) {
            if (retroCorePath.isNullOrBlank() || retroRomPath.isNullOrBlank() ||
                !validAbsolutePath(retroCorePath, true) ||
                !validAbsolutePath(retroRomPath, false)) {
                return mapOf("status" to "manual_only")
            }
            val intent = Intent().apply {
                setClassName(
                    emulator.packageName,
                    "com.retroarch.browser.retroactivity.RetroActivityFuture"
                )
                putExtra("ROM", retroRomPath)
                putExtra("LIBRETRO", retroCorePath)
            }
            return try {
                startActivity(intent)
                mapOf("status" to "handoff_requested_unverified")
            } catch (error: Exception) {
                mapOf("status" to "unsupported", "detail" to (error.message ?: ""))
            }
        }
        if (emulator.romLaunch != "view_unverified" &&
            emulator.romLaunch != "view_documented") {
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
            if (emulator.id.startsWith("ppsspp")) {
                setClassName(emulator.packageName, "org.ppsspp.ppsspp.PpssppActivity")
            } else {
                setPackage(emulator.packageName)
            }
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

    /** Passive diagnostics only: Flutter and emulators keep normal input ownership. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if ((event.source and InputDevice.SOURCE_GAMEPAD) ==
                InputDevice.SOURCE_GAMEPAD ||
            (event.source and InputDevice.SOURCE_DPAD) ==
                InputDevice.SOURCE_DPAD) {
            if (event.action == KeyEvent.ACTION_DOWN ||
                event.action == KeyEvent.ACTION_UP) {
                gamepadSink?.success(mapOf(
                    "type" to "key",
                    "device" to (event.device?.name ?: "Gamepad"),
                    "key" to KeyEvent.keyCodeToString(event.keyCode),
                    "action" to (if (event.action == KeyEvent.ACTION_DOWN) "down" else "up")
                ))
            }
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onGenericMotionEvent(event: MotionEvent): Boolean {
        if ((event.source and InputDevice.SOURCE_JOYSTICK) ==
                InputDevice.SOURCE_JOYSTICK &&
            event.actionMasked == MotionEvent.ACTION_MOVE) {
            val now = android.os.SystemClock.uptimeMillis()
            if (now - lastJoystickEventMs >= 65L) {
                lastJoystickEventMs = now
                gamepadSink?.success(mapOf(
                    "type" to "joystick",
                    "device" to (event.device?.name ?: "Gamepad"),
                    "x" to event.getAxisValue(MotionEvent.AXIS_X),
                    "y" to event.getAxisValue(MotionEvent.AXIS_Y)
                ))
            }
        }
        return super.onGenericMotionEvent(event)
    }

    override fun onDestroy() {
        gamepadSink = null
        pendingImport?.error("ACTIVITY_DESTROYED", "File selection cancelled", null)
        pendingImport = null
        scanner.shutdown()
        super.onDestroy()
    }
}
