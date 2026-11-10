package com.redclaw.jolven_flutter

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaRecorder
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import android.util.DisplayMetrics
import android.view.WindowManager

/**
 * Consent-based SCREEN-ONLY recorder (no audio, no privileged overlays).
 * Android 29+ MediaStore output, API 34+ one-time projection token semantics.
 */
class JolvenRecordingService : Service() {
    companion object {
        private const val CHANNEL_ID = "jolven_recording"
        private const val NOTIFICATION_ID = 4682
        private const val ACTION_START = "com.redclaw.jolven.START_CAPTURE"
        private const val ACTION_STOP = "com.redclaw.jolven.STOP_CAPTURE"
        private const val EXTRA_RESULT_CODE = "resultCode"
        private const val EXTRA_RESULT_DATA = "resultData"

        @Volatile var isRecording = false
            private set
        @Volatile var lastError: String? = null
            private set
        @Volatile var lastVideoUri: String? = null
            private set

        fun start(context: Context, resultCode: Int, consent: Intent) {
            val serviceIntent = Intent(context, JolvenRecordingService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, consent)
            }
            context.startForegroundService(serviceIntent)
        }

        fun stop(context: Context) {
            context.startService(Intent(context, JolvenRecordingService::class.java).apply {
                action = ACTION_STOP
            })
        }
    }

    private var recorder: MediaRecorder? = null
    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var recordingUri: Uri? = null
    private var descriptor: ParcelFileDescriptor? = null
    private var callback: MediaProjection.Callback? = null
    private var stopping = false
    private var started = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            finishRecording()
            return START_NOT_STICKY
        }
        if (intent?.action != ACTION_START || started || Build.VERSION.SDK_INT < 29) {
            if (Build.VERSION.SDK_INT < 29) lastError = "Recording needs Android 10+"
            if (!started) stopSelf()
            return START_NOT_STICKY
        }
        try {
            createNotificationChannel()
            val notification = makeNotification()
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(
                    NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
            startSession(intent)
        } catch (error: Exception) {
            lastError = error.message ?: "Could not start MediaProjection"
            finishRecording()
        }
        return START_NOT_STICKY
    }

    private fun createNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID, "Jolven — Screen Recording",
                NotificationManager.IMPORTANCE_LOW
            )
        )
    }

    private fun makeNotification(): Notification {
        val pendingStop = PendingIntent.getService(
            this, 0,
            Intent(this, JolvenRecordingService::class.java).apply {
                action = ACTION_STOP
            },
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle("Jolven — Recording screen")
            .setContentText("Recording with Android screen capture consent")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .addAction(
                Notification.Action.Builder(
                    android.R.drawable.ic_media_pause, "Stop", pendingStop
                ).build()
            )
            .build()
    }

    @Suppress("DEPRECATION")
    private fun startSession(intent: Intent) {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, 0)
        val data = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
        } else {
            intent.getParcelableExtra(EXTRA_RESULT_DATA)
        } ?: error("Screen capture consent data was lost")
        val manager = getSystemService(MediaProjectionManager::class.java)
        projection = manager.getMediaProjection(resultCode, data)
            ?: error("Android refused MediaProjection")
        val captured = projection ?: error("No MediaProjection")
        val projectionCallback = object : MediaProjection.Callback() {
            override fun onStop() {
                finishRecording()
            }
        }
        callback = projectionCallback
        captured.registerCallback(projectionCallback, Handler(Looper.getMainLooper()))

        val metrics = DisplayMetrics()
        val windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        windowManager.defaultDisplay.getRealMetrics(metrics)
        val rawWidth = metrics.widthPixels.coerceAtLeast(2)
        val rawHeight = metrics.heightPixels.coerceAtLeast(2)
        val scale = minOf(1.0, 1280.0 / maxOf(rawWidth, rawHeight))
        val width = ((rawWidth * scale).toInt().coerceAtLeast(2) / 2) * 2
        val height = ((rawHeight * scale).toInt().coerceAtLeast(2) / 2) * 2

        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, "Jolven-${System.currentTimeMillis()}.mp4")
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/Jolven")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val uri = contentResolver.insert(MediaStore.Video.Media.EXTERNAL_CONTENT_URI, values)
            ?: error("Android could not create a video file")
        recordingUri = uri
        descriptor = contentResolver.openFileDescriptor(uri, "w")
            ?: error("Android video destination is inaccessible")

        val encoder = MediaRecorder()
        recorder = encoder
        encoder.setVideoSource(MediaRecorder.VideoSource.SURFACE)
        encoder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        encoder.setVideoEncoder(MediaRecorder.VideoEncoder.H264)
        encoder.setVideoSize(width, height)
        encoder.setVideoFrameRate(30)
        encoder.setVideoEncodingBitRate(6_000_000)
        encoder.setOutputFile(descriptor!!.fileDescriptor)
        encoder.prepare()

        virtualDisplay = captured.createVirtualDisplay(
            "Jolven capture", width, height, metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            encoder.surface, null, null
        )
        encoder.start()
        started = true
        isRecording = true
        lastError = null
    }

    @Synchronized
    private fun finishRecording() {
        if (stopping) return
        stopping = true
        var videoOk = started
        if (started) {
            try {
                recorder?.stop()
            } catch (error: RuntimeException) {
                videoOk = false
                lastError = error.message ?: "Video was too short to finalize"
            }
        }
        isRecording = false
        started = false
        runCatching { virtualDisplay?.release() }
        virtualDisplay = null
        runCatching { recorder?.reset() }
        runCatching { recorder?.release() }
        recorder = null
        runCatching { descriptor?.close() }
        descriptor = null
        callback?.let { callback ->
            runCatching { projection?.unregisterCallback(callback) }
        }
        callback = null
        runCatching { projection?.stop() }
        projection = null

        recordingUri?.let { uri ->
            if (videoOk) {
                runCatching {
                    contentResolver.update(uri, ContentValues().apply {
                        put(MediaStore.Video.Media.IS_PENDING, 0)
                    }, null, null)
                    lastVideoUri = uri.toString()
                }
            } else {
                runCatching { contentResolver.delete(uri, null, null) }
            }
        }
        recordingUri = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        finishRecording()
        super.onDestroy()
    }
}
