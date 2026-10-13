package app.phonestudio

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.result.PickVisualMediaRequest
import androidx.lifecycle.ViewModelProvider
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.core.content.ContextCompat
import app.phonestudio.core.studioContainer
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.ui.StudioScreen
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.theme.PhoneStudioTheme

class MainActivity : ComponentActivity() {
    private lateinit var studioViewModel: StudioViewModel
    private val sourcePicker = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) studioViewModel.importSource(uri)
    }

    private var notificationPermissionResult: ((Boolean) -> Unit)? = null
    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            notificationPermissionResult?.invoke(granted)
            notificationPermissionResult = null
        }

    private var storagePermissionResult: ((Boolean) -> Unit)? = null
    private val storagePermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            storagePermissionResult?.invoke(granted)
            storagePermissionResult = null
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = applicationContext.studioContainer()
        studioViewModel = ViewModelProvider(this, StudioViewModel.factory(container))[StudioViewModel::class.java]

        setContent {
            PhoneStudioTheme {
                val state by studioViewModel.state.collectAsState()
                StudioScreen(
                    state = state,
                    viewModel = studioViewModel,
                    onNotifyChanged = { enabled ->
                        updateCompletionNotifications(studioViewModel, enabled)
                    },
                    onSaveImage = { image -> saveImage(studioViewModel, image) },
                    onPickImage = { sourcePicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                )
            }
        }
    }

    /**
     * Asked for when the user turns completion alerts on, rather than on every
     * cold start. The old build fired the prompt from onCreate whether or not
     * the feature was wanted, which trains people to dismiss it.
     */
    private fun updateCompletionNotifications(viewModel: StudioViewModel, enabled: Boolean) {
        if (!enabled || Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            viewModel.setNotifyOnCompletion(enabled)
            return
        }
        val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) {
            viewModel.setNotifyOnCompletion(true)
            return
        }

        notificationPermissionResult = { allowed ->
            viewModel.setNotifyOnCompletion(allowed)
            if (!allowed) viewModel.showNotice("Allow notifications to receive finished-render alerts.")
        }
        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun saveImage(viewModel: StudioViewModel, image: GeneratedImage) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            viewModel.saveToGallery(image)
            return
        }
        val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.WRITE_EXTERNAL_STORAGE) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) {
            viewModel.saveToGallery(image)
            return
        }

        storagePermissionResult = { allowed ->
            if (allowed) {
                viewModel.saveToGallery(image)
            } else {
                viewModel.showNotice("Allow storage access to save images on Android 8 or 9.")
            }
        }
        storagePermission.launch(Manifest.permission.WRITE_EXTERNAL_STORAGE)
    }
}
