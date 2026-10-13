@file:Suppress("DEPRECATION") // Owned native camera preview supports Android 8+ without a scanner service.

package app.phonestudio.ui.connect

import android.graphics.ImageFormat
import android.annotation.SuppressLint
import android.hardware.Camera
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.SystemClock
import android.view.Surface
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.WindowManager
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Panel
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Slate
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.ReaderException
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

/** Only composed after an explicit scan action and camera permission. No camera app or Play services needed. */
@Composable
internal fun SetupQrScanner(onResult: (String) -> Unit, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val maxDialogHeight = LocalConfiguration.current.screenHeightDp.dp * 0.88f
    val resultCallback by rememberUpdatedState(onResult)
    var cameraError by remember { mutableStateOf<String?>(null) }
    val cameraView = remember(context) {
        SetupCameraView(context, onCode = { resultCallback(it) }, onAvailable = { cameraError = null }, onUnavailable = {
            cameraError = "Camera unavailable. Close this scanner and paste the router setup code instead."
        })
    }
    DisposableEffect(cameraView, lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> cameraView.resumeCamera()
                Lifecycle.Event.ON_PAUSE, Lifecycle.Event.ON_STOP -> cameraView.pauseCamera()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) cameraView.resumeCamera()
        onDispose { lifecycle.removeObserver(observer); cameraView.disposeCamera() }
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier.fillMaxWidth().heightIn(max = maxDialogHeight).clip(RoundedCornerShape(24.dp)).background(Panel).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Scan your router QR", color = Mist, style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                TextButton(onClick = onDismiss, modifier = Modifier.semantics { contentDescription = "Close scanner" }) {
                    Text("Close", color = Periwinkle)
                }
            }
            Column(Modifier.fillMaxWidth().heightIn(max = maxDialogHeight * 0.25f).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Open Phone setup in the router notebook. Hold its QR inside the camera view.", color = Slate,
                    style = MaterialTheme.typography.bodyMedium)
                cameraError?.let { Text(it, color = Mist, style = MaterialTheme.typography.bodyMedium) }
            }
            // Header/Close are measured before this preview; short windows shrink the preview instead of losing the controls.
            Box(Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(16.dp)).background(Color.Black)) {
                AndroidView(factory = { cameraView }, modifier = Modifier.fillMaxSize())
            }
        }
    }
}

/** Camera and decode work share one owned looper; one frame at a time keeps allocation and CPU bounded. */
@Suppress("DEPRECATION")
@SuppressLint("ViewConstructor") // Compose constructs this private view with callbacks; it is never XML-inflated.
private class SetupCameraView(
    context: android.content.Context,
    private val onCode: (String) -> Unit,
    private val onAvailable: () -> Unit,
    private val onUnavailable: () -> Unit
) : SurfaceView(context), SurfaceHolder.Callback {
    private val thread = HandlerThread("studio-qr-camera").apply { start() }
    private val cameraHandler = Handler(thread.looper)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val reader = QRCodeReader()
    private val autoFocusToken = Any()
    private var camera: Camera? = null
    @Volatile private var foreground = false
    @Volatile private var surfaceReady = false
    @Volatile private var disposed = false
    @Volatile private var generation = 0
    private var found = false

    init { holder.addCallback(this) }

    fun resumeCamera() {
        if (disposed || foreground) return
        foreground = true
        generation++
        cameraHandler.post { found = false; openCamera() }
    }
    fun pauseCamera() {
        foreground = false
        generation++
        cameraHandler.post { releaseCamera() }
    }
    fun disposeCamera() {
        if (disposed) return
        disposed = true; foreground = false; generation++
        holder.removeCallback(this)
        mainHandler.removeCallbacksAndMessages(null)
        cameraHandler.removeCallbacksAndMessages(null)
        cameraHandler.post { releaseCamera(); thread.quitSafely() }
    }
    override fun surfaceCreated(holder: SurfaceHolder) { surfaceReady = true; cameraHandler.post { found = false; openCamera() } }
    override fun surfaceChanged(holder: SurfaceHolder, format: Int, width: Int, height: Int) = Unit
    override fun surfaceDestroyed(holder: SurfaceHolder) { surfaceReady = false; generation++; cameraHandler.post { releaseCamera() } }

    private fun openCamera() {
        if (disposed || !foreground || !surfaceReady || camera != null || found) return
        val expected = generation
        try {
            val info = Camera.CameraInfo()
            val cameraIds = (0 until Camera.getNumberOfCameras())
            val id = cameraIds.firstOrNull {
                Camera.getCameraInfo(it, info); info.facing == Camera.CameraInfo.CAMERA_FACING_BACK
            } ?: cameraIds.firstOrNull() ?: throw IllegalStateException()
            Camera.getCameraInfo(id, info)
            val opened = Camera.open(id)
            camera = opened
            val parameters = opened.parameters
            val sizes = parameters.supportedPreviewSizes ?: throw IllegalStateException()
            val size = sizes.filter { it.width * it.height <= 1280 * 720 }.maxByOrNull { it.width * it.height }
                ?: sizes.minByOrNull { it.width * it.height } ?: throw IllegalStateException()
            if (size.width * size.height > 1920 * 1080) throw IllegalStateException()
            parameters.setPreviewSize(size.width, size.height)
            parameters.previewFormat = ImageFormat.NV21
            if (Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE in parameters.supportedFocusModes.orEmpty()) {
                parameters.focusMode = Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE
            } else if (Camera.Parameters.FOCUS_MODE_AUTO in parameters.supportedFocusModes.orEmpty()) {
                parameters.focusMode = Camera.Parameters.FOCUS_MODE_AUTO
            }
            opened.parameters = parameters
            val rotation = (context.getSystemService(android.content.Context.WINDOW_SERVICE) as WindowManager).defaultDisplay.rotation
            val degrees = when (rotation) { Surface.ROTATION_90 -> 90; Surface.ROTATION_180 -> 180; Surface.ROTATION_270 -> 270; else -> 0 }
            val orientation = if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT)
                (360 - (info.orientation + degrees) % 360) % 360
                else (info.orientation - degrees + 360) % 360
            opened.setDisplayOrientation(orientation)
            opened.setPreviewDisplay(holder)
            if (disposed || !foreground || !surfaceReady || generation != expected) { releaseCamera(); return }
            opened.startPreview()
            mainHandler.post { if (!disposed && foreground && generation == expected) onAvailable() }
            if (parameters.focusMode == Camera.Parameters.FOCUS_MODE_AUTO) focusCamera(opened, expected)
            nextFrame(opened, expected)
        } catch (_: Exception) {
            releaseCamera()
            mainHandler.post { if (!disposed && foreground && generation == expected) onUnavailable() }
        }
    }

    /** AUTO needs an explicit focus action. Two-second retries handle a changing phone/screen distance without a busy loop. */
    private fun focusCamera(opened: Camera, expected: Int) {
        if (disposed || !foreground || !surfaceReady || camera !== opened || generation != expected || found) return
        runCatching { opened.cancelAutoFocus(); opened.autoFocus(null) }
        cameraHandler.postAtTime({ focusCamera(opened, expected) }, autoFocusToken, SystemClock.uptimeMillis() + 2000L)
    }

    private fun nextFrame(opened: Camera, expected: Int) {
        if (disposed || !foreground || !surfaceReady || camera !== opened || generation != expected || found) return
        try {
            opened.setOneShotPreviewCallback { data, sourceCamera ->
                if (disposed || !foreground || generation != expected || camera !== sourceCamera) return@setOneShotPreviewCallback
                try {
                    val size = sourceCamera.parameters.previewSize
                    val source = PlanarYUVLuminanceSource(data, size.width, size.height, 0, 0, size.width, size.height, false)
                    val result = reader.decode(BinaryBitmap(HybridBinarizer(source)), mapOf(
                        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE), DecodeHintType.TRY_HARDER to true
                    ))
                    found = true
                    releaseCamera()
                    mainHandler.post { if (!disposed && foreground && generation == expected) onCode(result.text) }
                } catch (_: ReaderException) {
                    cameraHandler.postDelayed({ nextFrame(opened, expected) }, 250)
                } catch (_: Exception) {
                    releaseCamera()
                    mainHandler.post { if (!disposed && foreground && generation == expected) onUnavailable() }
                } finally { reader.reset() }
            }
        } catch (_: Exception) {
            releaseCamera()
            mainHandler.post { if (!disposed && foreground && generation == expected) onUnavailable() }
        }
    }

    private fun releaseCamera() {
        cameraHandler.removeCallbacksAndMessages(autoFocusToken)
        val owned = camera; camera = null
        if (owned != null) {
            runCatching { owned.cancelAutoFocus() }
            runCatching { owned.setPreviewCallback(null) }
            runCatching { owned.stopPreview() }
            runCatching { owned.release() }
        }
    }
}
