package app.phonestudio.ui.connect

import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.phonestudio.data.model.ConnectionConfig
import app.phonestudio.data.model.ConnectionSetupCode
import app.phonestudio.data.model.SetupCodeException
import app.phonestudio.data.model.ConnectionState
import app.phonestudio.ui.BackendCard
import app.phonestudio.ui.StudioUiState
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.components.BackendDot
import app.phonestudio.ui.components.QuietButton
import app.phonestudio.ui.components.ScreenPadding
import app.phonestudio.ui.components.SectionLabel
import app.phonestudio.ui.components.StudioPanel
import app.phonestudio.ui.components.StudioTextField
import app.phonestudio.ui.theme.Ink
import app.phonestudio.ui.theme.Mint
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Night
import app.phonestudio.ui.theme.Peach
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Rose
import app.phonestudio.ui.theme.Slate
import app.phonestudio.ui.theme.backendAccent
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

@Composable
fun ConnectScreen(state: StudioUiState, viewModel: StudioViewModel) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    var editingId by rememberSaveable { mutableStateOf<String?>(null) }
    var addingNew by rememberSaveable { mutableStateOf(false) }
    var archivedExpanded by rememberSaveable { mutableStateOf(false) }
    var managementExpanded by rememberSaveable { mutableStateOf(false) }
    var pendingRemovalId by rememberSaveable { mutableStateOf<String?>(null) }
    var confirmForgetAll by rememberSaveable { mutableStateOf(false) }
    // Credential-bearing state stays in memory; it is never written to saved instance state.
    var codeInput by remember { mutableStateOf("") }
    var enteringCode by remember { mutableStateOf(false) }
    var setupError by remember { mutableStateOf<String?>(null) }
    var review by remember { mutableStateOf<ConnectionConfig?>(null) }
    var reviewError by remember { mutableStateOf<String?>(null) }
    var scanning by remember { mutableStateOf(false) }
    val routers = state.backends.filter { it.config.isRouter }
    val archived = state.backends.filterNot { it.config.isRouter }
    fun readCode(code: String) {
        codeInput = ""
        setupError = null
        reviewError = null
        try { review = ConnectionSetupCode.decode(code) }
        catch (error: SetupCodeException) { setupError = error.message }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        if (allowed) { scanning = true; setupError = null }
        else setupError = "Camera access was declined. Paste the router setup code instead, or allow camera access in phone settings."
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = ScreenPadding,
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text(
                    text = "Your studio",
                    color = Periwinkle,
                    style = MaterialTheme.typography.labelMedium
                )
                Text(
                    text = "Connect once. Start creating.",
                    color = Mist,
                    style = MaterialTheme.typography.headlineSmall
                )
                Text(
                    text = "Run your workers and router, then scan the router's phone QR. One connection brings the whole studio to this phone.",
                    color = Slate,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }

        item {
            StudioPanel(modifier = Modifier.animateContentSize()) {
                SectionLabel(if (routers.isEmpty()) "Quick setup" else "Update your connection")
                Spacer(Modifier.height(8.dp))
                Text("Open Phone setup in the router notebook. Your QR includes the connection details, so there is nothing to type.",
                    color = Slate, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(16.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    QuietButton("Scan QR", Modifier.weight(1f), onClick = {
                        if (!context.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) {
                            setupError = "This device has no camera. Paste the router setup code instead."
                        } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                            scanning = true; setupError = null
                        } else permission.launch(Manifest.permission.CAMERA)
                    })
                    QuietButton("Paste code", Modifier.weight(1f), onClick = {
                        val copied = clipboard.getText()?.text
                        if (copied.isNullOrBlank()) {
                            enteringCode = true
                            setupError = "Copy the phone setup code from the router notebook first, or paste it below."
                        } else readCode(copied)
                    })
                }
                if (enteringCode) {
                    Spacer(Modifier.height(12.dp))
                    StudioTextField(codeInput, onValueChange = {
                        if (it.length <= ConnectionSetupCode.MAX_CODE_LENGTH) { codeInput = it; setupError = null }
                        else setupError = "This setup code is too long. Copy a new code from the router notebook."
                    }, label = "Private setup code", placeholder = "PHONE-STUDIO:1:…", password = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
                    TextButton(onClick = { readCode(codeInput) }, modifier = Modifier.fillMaxWidth()) {
                        Text("Review connection", color = Periwinkle)
                    }
                }
                setupError?.let { Spacer(Modifier.height(10.dp)); Text(it, color = Peach, style = MaterialTheme.typography.bodyMedium) }
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = { enteringCode = !enteringCode; codeInput = "" }) { Text(if (enteringCode) "Hide code entry" else "Enter code", color = Slate) }
                    TextButton(onClick = {
                        val router = routers.firstOrNull()
                        if (router != null) editingId = router.config.id else addingNew = true
                    }) { Text("Manual setup", color = Slate) }
                }
                Text("Your QR and setup code contain private credentials. Connect only to your own notebook.",
                    color = Slate, style = MaterialTheme.typography.labelSmall)
            }
        }

        if (!state.credentialsEncrypted) {
            item {
                StudioPanel {
                    Text(
                        text = "Credentials could not be encrypted on this device. They are stored in the app's private storage, so keep this phone protected.",
                        color = Peach,
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
        }

        for (card in routers) {
            item(key = card.config.id) {
                BackendPanel(
                    card = card,
                    accentIndex = state.accentIndex(card.config.id),
                    editing = editingId == card.config.id,
                    onToggleEdit = { editingId = if (editingId == card.config.id) null else card.config.id },
                    onSave = { updated ->
                        if (viewModel.saveConnection(updated)) editingId = null
                    },
                    onTest = { viewModel.checkBackend(card.config.id) },
                    onEnabledChange = { viewModel.setConnectionEnabled(card.config.id, it) },
                    onRemove = {
                        pendingRemovalId = card.config.id
                    }
                )
            }
        }

        if (state.routerWorkers.isNotEmpty()) {
            item {
                StudioPanel {
                    SectionLabel("Image workers", marker = "${state.routerWorkers.count { it.online }} / ${state.routerWorkers.size} online")
                    Spacer(Modifier.height(12.dp))
                    state.routerWorkers.forEachIndexed { index, worker ->
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            BackendDot(if (worker.online) Mint else Rose)
                            Column(Modifier.weight(1f)) {
                                Text(worker.name.ifBlank { worker.workerId }, color = Mist, style = MaterialTheme.typography.bodyMedium)
                                if (!worker.online && worker.message.isNotBlank()) Text(worker.message, color = Slate, style = MaterialTheme.typography.labelSmall)
                            }
                            Text(if (worker.online) "Online" else "Offline", color = if (worker.online) Mint else Peach, style = MaterialTheme.typography.labelMedium)
                        }
                        if (index != state.routerWorkers.lastIndex) Spacer(Modifier.height(12.dp))
                    }
                }
            }
        }

        if (addingNew) {
            item {
                BackendEditor(
                    title = "Router connection",
                    initial = ConnectionConfig(name = "Studio router", isRouter = true),
                    accentIndex = state.backends.size,
                    onSave = { updated ->
                        if (viewModel.saveConnection(updated)) addingNew = false
                    },
                    onCancel = { addingNew = false }
                )
            }
        }

        if (archived.isNotEmpty()) {
            item {
                QuietButton(if (archivedExpanded) "Hide previous connections" else "Previous connections · ${archived.size}", accent = Slate,
                    onClick = { archivedExpanded = !archivedExpanded })
            }
            if (archivedExpanded) {
                item { Text("Kept for your existing library images. New renders go through the router.", color = Slate, style = MaterialTheme.typography.bodySmall) }
                archived.forEach { card ->
                    item(key = card.config.id) {
                        BackendPanel(card, state.accentIndex(card.config.id), editingId == card.config.id,
                            onToggleEdit = { editingId = if (editingId == card.config.id) null else card.config.id },
                            onSave = { if (viewModel.saveConnection(it)) editingId = null },
                            onTest = { viewModel.checkBackend(card.config.id) },
                            onEnabledChange = { viewModel.setConnectionEnabled(card.config.id, it) },
                            onRemove = { pendingRemovalId = card.config.id })
                    }
                }
            }
        }

        if (state.hasAnyBackend) {
            item {
                TextButton(onClick = { managementExpanded = !managementExpanded }, modifier = Modifier.fillMaxWidth()) {
                    Text(if (managementExpanded) "Hide connection management" else "Connection management", color = Slate)
                }
            }
            if (managementExpanded) {
                item {
                    TextButton(onClick = viewModel::checkAllBackends, modifier = Modifier.fillMaxWidth()) {
                        Text("Test all saved connections", color = Periwinkle)
                    }
                    TextButton(onClick = { confirmForgetAll = true }, modifier = Modifier.fillMaxWidth()) {
                        Text("Forget everything on this phone", color = Rose)
                    }
                }
            }
        }
    }

    if (scanning) SetupQrScanner(onDismiss = { scanning = false }, onResult = {
        scanning = false
        readCode(it)
    })

    review?.let { config ->
        AlertDialog(
            onDismissRequest = { review = null; reviewError = null },
            title = { Text(if (routers.isEmpty()) "Connect to your studio?" else "Update your studio connection?") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(config.displayName, style = MaterialTheme.typography.titleMedium)
                    Text(config.serverUrl.toHttpUrlOrNull()?.host.orEmpty(), color = Periwinkle)
                    Text(if (routers.isEmpty()) "Your connection details will be saved privately on this phone. Connect only if this is your router notebook."
                        else "This updates the saved router. Your library and saved render records stay in place. Connect only if this is your router notebook.")
                    reviewError?.let { Text(state.notice.ifBlank { it }, color = Peach) }
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    if (viewModel.importConnection(config)) {
                        review = null; reviewError = null; enteringCode = false; editingId = null; addingNew = false
                    } else reviewError = "The connection could not be saved. Check the connection and try again."
                }) { Text("Connect") }
            },
            dismissButton = { TextButton(onClick = { review = null; reviewError = null }) { Text("Cancel") } }
        )
    }

    pendingRemovalId?.let { id ->
        val name = state.backends.firstOrNull { it.config.id == id }?.config?.displayName ?: "this backend"
        AlertDialog(
            onDismissRequest = { pendingRemovalId = null },
            title = { Text("Remove $name?") },
            text = {
                Text("Its saved credentials will be removed. Existing Drive images are not deleted, but this phone will no longer be able to load their library tiles.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.removeConnection(id)
                        if (editingId == id) editingId = null
                        pendingRemovalId = null
                    }
                ) { Text("Remove", color = Rose) }
            },
            dismissButton = {
                TextButton(onClick = { pendingRemovalId = null }) { Text("Keep") }
            }
        )
    }

    if (confirmForgetAll) {
        AlertDialog(
            onDismissRequest = { confirmForgetAll = false },
            title = { Text("Forget everything on this phone?") },
            text = {
                Text("This removes all backends, settings, library metadata, and the active batch. Files in Google Drive and images already saved to the phone stay untouched.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmForgetAll = false
                        editingId = null
                        addingNew = false
                        viewModel.forgetEverything()
                    }
                ) { Text("Forget everything", color = Rose) }
            },
            dismissButton = {
                TextButton(onClick = { confirmForgetAll = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun BackendPanel(
    card: BackendCard,
    accentIndex: Int,
    editing: Boolean,
    onToggleEdit: () -> Unit,
    onSave: (ConnectionConfig) -> Unit,
    onTest: () -> Unit,
    onEnabledChange: (Boolean) -> Unit,
    onRemove: () -> Unit
) {
    var detailsExpanded by rememberSaveable(card.config.id) { mutableStateOf(false) }
    val accent = backendAccent(accentIndex)
    val statusColor = when (card.status.state) {
        ConnectionState.ONLINE -> Mint
        ConnectionState.CHECKING -> Peach
        ConnectionState.OFFLINE -> Rose
        ConnectionState.UNKNOWN -> Slate
    }

    StudioPanel(modifier = Modifier.animateContentSize()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            BackendDot(color = accent, size = 10)
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = card.config.displayName,
                    color = Mist,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = card.status.message.ifBlank { "Not checked yet" },
                    color = statusColor,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Switch(
                checked = card.config.enabled,
                onCheckedChange = onEnabledChange,
                colors = SwitchDefaults.colors(checkedTrackColor = accent, checkedThumbColor = Ink)
            )
        }

        Spacer(Modifier.height(10.dp))
        Text(
            text = card.config.serverUrl.toHttpUrlOrNull()?.host ?: "No server address saved",
            color = Slate,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )

        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            QuietButton(
                label = if (editing) "Close" else "Edit",
                modifier = Modifier.weight(1f),
                accent = accent,
                onClick = onToggleEdit
            )
            QuietButton(label = "Test", modifier = Modifier.weight(1f), accent = accent, onClick = onTest)
        }

        if (card.status.message.isNotBlank()) {
            TextButton(onClick = { detailsExpanded = !detailsExpanded }) {
                Text(if (detailsExpanded) "Hide status details" else "Status details", color = Slate, style = MaterialTheme.typography.labelSmall)
            }
            if (detailsExpanded) Text(card.status.message, color = statusColor, style = MaterialTheme.typography.bodySmall)
        }

        if (editing) {
            Spacer(Modifier.height(14.dp))
            BackendEditor(
                title = "Edit ${card.config.displayName}",
                initial = card.config,
                accentIndex = accentIndex,
                embedded = true,
                onSave = onSave,
                onCancel = onToggleEdit,
                onRemove = onRemove
            )
        }
    }
}

/**
 * Advanced fallback for old sessions and devices without a usable camera.
 */
@Composable
private fun BackendEditor(
    title: String,
    initial: ConnectionConfig,
    accentIndex: Int,
    embedded: Boolean = false,
    onSave: (ConnectionConfig) -> Unit,
    onCancel: () -> Unit,
    onRemove: (() -> Unit)? = null
) {
    val context = LocalContext.current
    val accent = backendAccent(accentIndex)
    var draft by remember(initial.id) { mutableStateOf(initial) }
    var notebookError by remember { mutableStateOf<String?>(null) }

    val body: @Composable () -> Unit = {
        Column {
            SectionLabel(title)
            Spacer(Modifier.height(11.dp))
            StudioTextField(
                value = draft.name,
                onValueChange = { draft = draft.copy(name = it) },
                label = "Connection name",
                placeholder = "My studio"
            )
            Spacer(Modifier.height(10.dp))
            StudioTextField(
                value = draft.serverUrl,
                onValueChange = { draft = draft.copy(serverUrl = it) },
                label = "Server URL",
                placeholder = "https://…ngrok…",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri)
            )
            Spacer(Modifier.height(10.dp))
            StudioTextField(
                value = draft.tunnelUser,
                onValueChange = { draft = draft.copy(tunnelUser = it) },
                label = "Tunnel username",
                placeholder = "studio"
            )
            Spacer(Modifier.height(10.dp))
            StudioTextField(
                value = draft.tunnelPassword,
                onValueChange = { draft = draft.copy(tunnelPassword = it) },
                label = "Tunnel password",
                placeholder = "From the Colab cell",
                password = true
            )
            Spacer(Modifier.height(10.dp))
            StudioTextField(
                value = draft.studioToken,
                onValueChange = { draft = draft.copy(studioToken = it) },
                label = "Studio token",
                placeholder = "From the Colab cell",
                password = true
            )
            Spacer(Modifier.height(10.dp))
            StudioTextField(
                value = draft.colabUrl,
                onValueChange = { draft = draft.copy(colabUrl = it) },
                label = "Notebook link (optional)",
                placeholder = "https://colab.research.google.com/…"
            )

            Spacer(Modifier.height(8.dp))
            Text(
                text = "These values are available in the notebook's advanced connection details. Quick setup fills them for you.",
                color = Slate,
                style = MaterialTheme.typography.labelSmall
            )

            Spacer(Modifier.height(14.dp))
            Button(
                modifier = Modifier.fillMaxWidth(),
                onClick = { onSave(draft) },
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(containerColor = accent, contentColor = Ink)
            ) {
                Text(text = "Save and test", style = MaterialTheme.typography.labelMedium)
            }

            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                QuietButton(
                    label = "Open Colab",
                    modifier = Modifier.weight(1f),
                    accent = Slate,
                    onClick = {
                        val destination = draft.colabUrl.trim().ifBlank { "https://colab.research.google.com/" }
                        val parsed = destination.toHttpUrlOrNull()
                        if (parsed == null || parsed.scheme != "https" || parsed.username.isNotEmpty() || parsed.password.isNotEmpty()) {
                            notebookError = "Add a complete HTTPS notebook link without embedded credentials."
                        } else {
                            notebookError = null
                            try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(destination))) }
                            catch (_: ActivityNotFoundException) { notebookError = "No browser is available to open the notebook." }
                            catch (_: SecurityException) { notebookError = "This device could not open the notebook link." }
                        }
                    }
                )
                QuietButton(label = "Cancel", modifier = Modifier.weight(1f), accent = Slate, onClick = onCancel)
            }

            notebookError?.let { Text(it, color = Peach, style = MaterialTheme.typography.bodySmall) }

            if (onRemove != null) {
                Spacer(Modifier.height(4.dp))
                TextButton(onClick = onRemove, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "Remove this backend",
                        color = Rose,
                        style = MaterialTheme.typography.labelMedium
                    )
                }
            }
        }
    }

    if (embedded) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(16.dp))
                .background(Night)
                .border(1.dp, accent.copy(alpha = 0.25f), RoundedCornerShape(16.dp))
                .padding(14.dp)
        ) { body() }
    } else {
        StudioPanel { body() }
    }
}
