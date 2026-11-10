# Jolven Android — MediaProjection recorder (initial implementation of #87)

Implementation adapted architecturally from Kwiq's `ScreenRecordService.kt` and `MediaProjectionIntents.kt`, **without** reusing Kwiq's HOME launcher, resource strings or Compose UI.

## Safety contract

- Video-only screen capture, no audio or facecam. The user explicitly clicks Record, consents through Android `createScreenCaptureIntent()`, and a foreground service runs with `FOREGROUND_SERVICE_MEDIA_PROJECTION`, its own notification and Stop action.
- On Android 14+, each consent token is used for **one** `getMediaProjection` and **one** `createVirtualDisplay`. Consent is never persisted. The service registers `MediaProjection.Callback` before creating the virtual display and ends the session when projection is revoked.
- Saving to a MediaStore `Movies/Jolven` MP4 in Android 10+ (API29). Earlier Android versions remain supported for the gaming hub but the recorder is unavailable to avoid legacy broad storage permissions.
- Video format H.264 MP4, screen aspect ratio clamped to 1280 px maximum edge, 30 FPS, nominal 6Mbps. Encoder and dimensions can fail on some devices; error state is exposed and incomplete MediaStore items are removed when possible.
- No capture without user consent, no AccessibilityService, no stealth recording, no bypass of protected surfaces. Pause/rotation and capture sizes for Android 14 app-window sharing require hardware tests.

## Remaining #87 criteria

- Microphone/internal audio and applicable consent requirements, facecam, pause/resume, user selectable resolution/FPS/bitrate, real device QA for Android14+ token behavior, loss of service and rotation, Quick Settings Tile, optional capture linked to a game, playback UI and release privacy notice.
- Users can stop via Jolven's screen or the foreground notification when another app is visible.

Official Android policy: https://developer.android.com/media/grow/media-projection
Legacy reference: https://github.com/zonaro/Kwiq/blob/main/app/src/main/java/br/com/redclaw/kwiq/ScreenRecordService.kt
