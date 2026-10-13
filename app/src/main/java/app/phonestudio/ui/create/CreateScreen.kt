package app.phonestudio.ui.create

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.CanvasFormat
import app.phonestudio.data.model.ConnectionState
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.RenderPace
import app.phonestudio.data.model.Seeds
import app.phonestudio.ui.StudioTab
import app.phonestudio.ui.StudioUiState
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.library.ImageViewer
import app.phonestudio.ui.components.BackendDot
import app.phonestudio.ui.components.ChoiceChip
import app.phonestudio.ui.components.DisclosurePanel
import app.phonestudio.ui.components.MetricSlider
import app.phonestudio.ui.components.QuietButton
import app.phonestudio.ui.components.ScreenPadding
import app.phonestudio.ui.components.SectionLabel
import app.phonestudio.ui.components.SelectMenu
import app.phonestudio.ui.components.StudioPanel
import app.phonestudio.ui.components.StudioTextField
import app.phonestudio.ui.components.ThinProgress
import app.phonestudio.ui.theme.Ink
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Mint
import app.phonestudio.ui.theme.Night
import app.phonestudio.ui.theme.PanelRaised
import app.phonestudio.ui.theme.Peach
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Rose
import app.phonestudio.ui.theme.Slate
import app.phonestudio.ui.theme.backendAccent
import coil.compose.AsyncImage
import coil.request.ImageRequest
import java.util.Locale

@Composable
fun CreateScreen(
    state: StudioUiState,
    viewModel: StudioViewModel,
    onNotifyChanged: (Boolean) -> Unit,
    onSaveImage: (GeneratedImage) -> Unit,
    onPickImage: () -> Unit
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = ScreenPadding,
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item(key = "heading") { Masthead(backendCount = state.readyBackends.size) }
        item(key = "connection") { BackendRail(state = state, onOpenConnect = { viewModel.selectTab(StudioTab.CONNECT) }) }
        item(key = "mode") {
            Row(modifier = Modifier.selectableGroup(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChoiceChip("Generate", detail = null, selected = !state.editDraft.enabled, modifier = Modifier.weight(1f)) {
                    viewModel.updateEdit { it.copy(enabled = false) }
                }
                ChoiceChip("Edit image", detail = null, selected = state.editDraft.enabled, modifier = Modifier.weight(1f)) {
                    viewModel.updateEdit { it.copy(enabled = true) }
                }
            }
        }
        if (state.editDraft.enabled) item(key = "edit-draft") { EditPanel(state, viewModel, onPickImage) }
        else item(key = "prompt-draft") {
            PromptCard(
                params = state.parameters,
                onChange = { updated -> viewModel.updateParameters { updated } }
            )
        }
        if (state.latestResults.isNotEmpty()) {
            item(key = "results") { ResultStrip(state = state, viewModel = viewModel, onSaveImage = onSaveImage) }
        }
        state.batch?.takeIf { !it.isActive }
            ?.unsuccessful
            ?.takeIf { it.isNotEmpty() }
            ?.let { failures ->
                item(key = "failures") { FailureCard(failures = failures, onRetry = viewModel::retryFailedBackends) }
            }
        item(key = "render-settings") {
            DisclosurePanel(
                title = "Render settings",
                summary = "${state.parameters.width} × ${state.parameters.height} · ${state.parameters.steps} steps · " +
                    state.parameters.model.substringAfterLast('/').ifBlank { "Choose a model" }
            ) {
                ModelCard(
                    params = state.parameters,
                    checkpoints = state.catalog.checkpoints,
                    onChoose = viewModel::chooseModel,
                    onOpenModels = { viewModel.selectTab(StudioTab.MODELS) }
                )
                Spacer(Modifier.height(20.dp))
                FormatCard(params = state.parameters, onChange = { updated -> viewModel.updateParameters { updated } })
                Spacer(Modifier.height(20.dp))
                PaceCard(params = state.parameters, onChange = { updated -> viewModel.updateParameters { updated } })
            }
        }
        item(key = "advanced") {
            AdvancedCard(
                params = state.parameters,
                loras = state.catalog.loras,
                backendCount = state.routerWorkers.size,
                onChange = { updated -> viewModel.updateParameters { updated } }
            )
        }
        item(key = "assistant-settings") {
            DisclosurePanel(
                title = "Assistant & preferences",
                summary = if (state.parameters.reviewCandidates) "Chooses the closest match · originals stay saved" else "Image review off · every version stays available"
            ) {
                if (!state.editDraft.enabled) ToggleRow("Improve my prompt", "Converts your description to tags. Your original text stays saved.", state.parameters.enhancePrompt) { enabled ->
                    viewModel.updateParameters { it.copy(enhancePrompt = enabled) }
                }
                Spacer(Modifier.height(8.dp))
                ToggleRow("Choose the closest match", "Reviews the actual images. Other versions stay available.", state.parameters.reviewCandidates) { enabled ->
                    viewModel.updateParameters { it.copy(reviewCandidates = enabled) }
                }
                Spacer(Modifier.height(8.dp))
                ToggleRow(
                    title = "Extra acceleration",
                    detail = "Preference saved. Workers in compatibility mode keep optional acceleration off.",
                    checked = state.parameters.speedExtras,
                    onCheckedChange = { enabled -> viewModel.updateParameters { it.copy(speedExtras = enabled) } }
                )
                Spacer(Modifier.height(8.dp))
                ToggleRow(
                    title = "Notify when ready",
                    detail = "One notification when the render finishes.",
                    checked = state.notifyOnCompletion,
                    onCheckedChange = onNotifyChanged
                )
            }
        }
    }
}

@Composable
private fun Masthead(backendCount: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(text = "Phone Studio", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
        Text(
            text = "Your next image",
            color = Mist,
            style = MaterialTheme.typography.displaySmall,
        )
        Text(
            text = when (backendCount) {
                0 -> "Connect your router to begin."
                else -> "Describe a scene, or make a careful edit."
            },
            color = Slate,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

/** Quiet while idle; worker progress opens automatically during a render. */
@Composable
private fun BackendRail(state: StudioUiState, onOpenConnect: () -> Unit) {
    val backends = state.backends.filter { it.config.isRouter }
    var showDetails by rememberSaveable { mutableStateOf(false) }
    if (backends.isEmpty()) {
        StudioPanel {
            Text(text = "Connect your router", color = Mist, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Scan the connection QR from your router notebook, or paste its connection card.",
                color = Slate,
                style = MaterialTheme.typography.bodyMedium
            )
            Spacer(Modifier.height(11.dp))
            QuietButton(label = "Connect router", onClick = onOpenConnect)
        }
        return
    }

    val router = backends.first()
    val workers = state.batch?.targets?.firstOrNull()?.routerWorkers?.takeIf { state.isGenerating && it.isNotEmpty() }
        ?: state.routerWorkers
    val statusColor = when {
        !router.config.enabled -> Slate
        router.status.state == ConnectionState.ONLINE -> Mint
        router.status.state == ConnectionState.OFFLINE -> Rose
        else -> Slate
    }
    StudioPanel(modifier = Modifier.animateContentSize()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(9.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            BackendDot(statusColor, size = 9)
            Column(Modifier.weight(1f)) {
                Text(
                    text = when {
                        !router.config.enabled -> "Router paused"
                        router.status.state == ConnectionState.ONLINE -> "Router connected"
                        router.status.state == ConnectionState.CHECKING -> "Checking connection…"
                        router.status.state == ConnectionState.OFFLINE -> "Router needs attention"
                        else -> "Router not checked yet"
                    },
                    color = Mist,
                    style = MaterialTheme.typography.titleMedium
                )
                Text(
                    text = if (state.isGenerating) state.batch?.summary.orEmpty().ifBlank { "Rendering…" }
                        else if (workers.isEmpty()) "Workers not checked yet"
                        else "${workers.count { it.online }} of ${workers.size} workers online",
                    color = statusColor,
                    style = MaterialTheme.typography.labelSmall
                )
            }
            TextButton(onClick = onOpenConnect) { Text("Manage", color = Periwinkle) }
        }
        if (!state.isGenerating) {
            TextButton(onClick = { showDetails = !showDetails }) {
                Text(if (showDetails) "Hide details" else "Connection details", color = Slate, style = MaterialTheme.typography.labelSmall)
            }
        }
        if (showDetails || state.isGenerating) {
            Spacer(Modifier.height(8.dp))
            workers.forEachIndexed { index, worker ->
                BackendColumn(
                    name = worker.name,
                    detail = worker.error ?: if (state.isGenerating) worker.stage.ifBlank { worker.message }
                        else worker.message.ifBlank { if (worker.online) "Online" else "Not reachable" },
                    accent = backendAccent(index),
                    dimmed = worker.state in setOf("failed", "skipped", "cancelled") || (!state.isGenerating && !worker.online),
                    progress = if (worker.stepsTotal > 0) (worker.stepsDone.toFloat() / worker.stepsTotal).coerceIn(0f, 1f) else null,
                    busy = state.isGenerating && worker.state !in setOf("complete", "failed", "skipped", "cancelled"),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(6.dp))
            }
            Text(
                router.status.message.ifBlank { "Open Manage to check the router." },
                color = Slate,
                style = MaterialTheme.typography.labelSmall
            )
        }
    }
}

@Composable
private fun BackendColumn(
    name: String,
    detail: String,
    accent: Color,
    dimmed: Boolean,
    progress: Float?,
    busy: Boolean,
    modifier: Modifier
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(Night)
            .border(1.dp, accent.copy(alpha = if (dimmed) 0.12f else 0.4f), RoundedCornerShape(14.dp))
            .padding(horizontal = 10.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            BackendDot(color = if (dimmed) Slate else accent, size = 8)
            Text(
                text = name,
                color = if (dimmed) Slate else Mist,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Text(
            text = detail,
            color = Slate,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis
        )
        if (busy) ThinProgress(progress = progress, accent = accent)
    }
}

@Composable
private fun PromptCard(params: GenerationParameters, onChange: (GenerationParameters) -> Unit) {
    var showNegative by rememberSaveable { mutableStateOf(false) }
    StudioPanel(modifier = Modifier.animateContentSize()) {
        SectionLabel("Scene")
        Spacer(Modifier.height(12.dp))
        StudioTextField(
            value = params.prompt,
            onValueChange = { onChange(params.copy(prompt = it)) },
            label = "Describe the image",
            placeholder = "A midnight greenhouse drifting through a city of clouds…",
            minLines = 4
        )
        TextButton(
            onClick = { showNegative = !showNegative },
            contentPadding = PaddingValues(top = 7.dp, bottom = 0.dp)
        ) {
            Text(
                text = if (showNegative) "Hide negative prompt" else "Edit negative prompt",
                color = Periwinkle,
                style = MaterialTheme.typography.labelMedium
            )
        }
        if (showNegative) {
            StudioTextField(
                value = params.negativePrompt,
                onValueChange = { onChange(params.copy(negativePrompt = it)) },
                label = "Avoid",
                placeholder = "low quality, watermark, text",
                minLines = 2
            )
        }
        Spacer(Modifier.height(7.dp))
        Text(
            text = "Prompts and settings are saved automatically.",
            color = Slate,
            style = MaterialTheme.typography.labelSmall
        )
    }
}

@Composable
private fun ModelCard(
    params: GenerationParameters,
    checkpoints: List<String>,
    onChoose: (String) -> Unit,
    onOpenModels: () -> Unit
) {
    Column {
        SectionLabel("Model")
        Spacer(Modifier.height(11.dp))
        if (checkpoints.isEmpty()) {
            Text(
                text = if (params.model.isNotBlank()) "Saved checkpoint" else "No checkpoints visible yet.",
                color = Mist,
                style = MaterialTheme.typography.titleMedium
            )
            if (params.model.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = params.model,
                    color = Periwinkle,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                text = if (params.model.isNotBlank()) {
                    "Your choice is kept. The model list is not loaded or is empty; reconnect or refresh in Models to change it."
                } else {
                    "Add one from Civitai, or drop a SafeTensors file into Drive and refresh."
                },
                color = Slate,
                style = MaterialTheme.typography.bodyMedium
            )
            Spacer(Modifier.height(10.dp))
            QuietButton(label = "Open models", onClick = onOpenModels)
        } else {
            SelectMenu(
                label = "Checkpoint",
                value = params.model,
                options = checkpoints,
                placeholder = "Choose a checkpoint",
                onChoose = onChoose
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Backends without this file are skipped for the batch rather than swapped to another model.",
                color = Slate,
                style = MaterialTheme.typography.labelSmall
            )
        }
    }
}

@Composable
private fun FormatCard(params: GenerationParameters, onChange: (GenerationParameters) -> Unit) {
    Column {
        SectionLabel("Canvas")
        Spacer(Modifier.height(11.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().selectableGroup()) {
            CanvasFormat.entries.forEach { format ->
                ChoiceChip(
                    label = format.label,
                    detail = format.sizeLabel,
                    selected = params.width == format.width && params.height == format.height,
                    modifier = Modifier.weight(1f)
                ) {
                    onChange(params.copy(width = format.width, height = format.height))
                }
            }
        }
    }
}

@Composable
private fun PaceCard(
    params: GenerationParameters,
    onChange: (GenerationParameters) -> Unit
) {
    Column {
        SectionLabel("Render pace")
        Spacer(Modifier.height(11.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth().selectableGroup()) {
            RenderPace.entries.forEach { pace ->
                ChoiceChip(
                    label = pace.label,
                    detail = "${pace.steps} steps",
                    selected = params.steps == pace.steps,
                    modifier = Modifier.weight(1f)
                ) {
                    onChange(pace.applyTo(params))
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        Text(
            text = (RenderPace.forSteps(params.steps) ?: RenderPace.BALANCED).detail,
            color = Slate,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

@Composable
private fun AdvancedCard(
    params: GenerationParameters,
    loras: List<String>,
    backendCount: Int,
    onChange: (GenerationParameters) -> Unit
) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    StudioPanel(modifier = Modifier.animateContentSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .semantics { stateDescription = if (expanded) "Expanded" else "Collapsed" }
                .clickable(role = Role.Button) { expanded = !expanded },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                SectionLabel("Seed & style")
                Text(
                    text = "Seed and optional style LoRA",
                    color = Slate,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Text(text = if (expanded) "−" else "+", color = Periwinkle, fontSize = 26.sp)
        }
        if (!expanded) return@StudioPanel

        Spacer(Modifier.height(14.dp))
        StudioTextField(
            value = if (params.seed < 0) "" else params.seed.toString(),
            onValueChange = { raw ->
                onChange(params.copy(seed = raw.trim().toLongOrNull()?.coerceAtLeast(0L) ?: Seeds.AUTO))
            },
            label = "Seed",
            placeholder = "Random every time",
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            trailing = if (params.seed >= 0) {
                {
                    TextButton(onClick = { onChange(params.copy(seed = Seeds.AUTO)) }) {
                        Text("Clear", color = Periwinkle, style = MaterialTheme.typography.labelSmall)
                    }
                }
            } else {
                null
            }
        )
        if (backendCount > 1) {
            Spacer(Modifier.height(12.dp))
            ToggleRow(
                title = "Vary the seed per backend",
                detail = "On: the first backend renders your seed and the others step up from it. " +
                    "Off: every backend renders the same seed, which is how you compare two checkpoints fairly.",
                checked = params.varySeedPerBackend,
                onCheckedChange = { onChange(params.copy(varySeedPerBackend = it)) }
            )
        }
        // A saved style must remain clearable while its backend is offline.
        if (loras.isNotEmpty() || params.lora.isNotBlank()) {
            Spacer(Modifier.height(12.dp))
            SelectMenu(
                label = "LoRA (optional)",
                value = params.lora.ifBlank { "None" },
                options = listOf("None") + loras,
                onChoose = { selection ->
                    onChange(params.copy(lora = if (selection == "None") "" else selection))
                }
            )
            if (params.lora.isNotBlank()) {
                Spacer(Modifier.height(10.dp))
                MetricSlider(
                    label = "LoRA weight",
                    valueText = String.format(Locale.US, "%.2f", params.loraStrength),
                    value = params.loraStrength,
                    range = 0f..1.5f,
                    steps = 14,
                    onValueChange = { onChange(params.copy(loraStrength = (it * 100).toInt() / 100f)) }
                )
            }
        }
    }
}

@Composable
private fun ToggleRow(
    title: String,
    detail: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Night)
            .padding(horizontal = 13.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, color = Mist, style = MaterialTheme.typography.titleMedium)
            Text(text = detail, color = Slate, style = MaterialTheme.typography.labelSmall)
        }
        Switch(checked = checked, onCheckedChange = onCheckedChange, modifier = Modifier.semantics { contentDescription = title })
    }
}

@Composable
fun CreateActionBar(
    state: StudioUiState,
    onGenerate: () -> Unit,
    onCancel: () -> Unit
) {
    val busy = state.isGenerating
    val targets = state.readyBackends.size
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val blockedReason = when {
        state.isPreparingEdit -> "Preparing the source image…"
        targets == 0 -> "Connect and enable your router to begin."
        state.parameters.model.isBlank() -> "Choose a checkpoint in Models."
        state.editDraft.enabled && !state.editDraft.hasSource -> "Choose an image to edit."
        state.editDraft.enabled && state.editDraft.maskMode == "manual" && state.editDraft.strokes.isEmpty() -> "Paint the area to change, or choose Automatic area."
        state.editDraft.enabled && state.editDraft.instruction.isBlank() -> "Describe the change you want."
        !state.editDraft.enabled && state.parameters.prompt.isBlank() -> "Describe the image in the scene field."
        else -> null
    }

    Surface(color = Night) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            val message = if (busy) {
                state.batch?.summary?.takeIf { it.isNotBlank() } ?: "A render is running."
            } else blockedReason
            if (message != null) {
                Text(
                    text = message,
                    color = if (busy) Peach else Slate,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
            Button(
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
                onClick = {
                    focusManager.clearFocus()
                    keyboard?.hide()
                    if (busy) onCancel() else onGenerate()
                },
                enabled = busy || blockedReason == null,
                shape = RoundedCornerShape(18.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (busy) Rose else Periwinkle,
                    contentColor = Ink,
                    disabledContainerColor = PanelRaised,
                    disabledContentColor = Slate
                )
            ) {
                Text(
                    text = if (busy) "Stop" else if (state.editDraft.enabled) "Make the edit" else "Generate image",
                    style = MaterialTheme.typography.labelMedium
                )
            }
            if (busy) {
                Text(
                    text = "An accepted image may still finish on Colab.",
                    color = Slate,
                    style = MaterialTheme.typography.labelSmall
                )
            }
        }
    }
}

/**
 * Every image from the batch, side by side, each tagged with the backend and
 * seed that produced it. Horizontal because comparing backends is the point.
 */
@Composable
private fun ResultStrip(
    state: StudioUiState,
    viewModel: StudioViewModel,
    onSaveImage: (GeneratedImage) -> Unit
) {
    var showOthers by rememberSaveable(state.batch?.batchId) { mutableStateOf(false) }
    val results = state.latestResults.filter { showOthers || it.visibleByDefault }
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    val selected = results.firstOrNull { it.id == selectedId }
    StudioPanel {
        SectionLabel("Latest result", marker = "${state.latestResults.size} versions")
        if (state.latestResults.any { !it.visibleByDefault }) {
            TextButton(onClick = { showOthers = !showOthers }) { Text(if (showOthers) "Show the chosen image" else "Other versions", color = Periwinkle) }
        }
        state.latestResults.firstOrNull()?.let { image ->
            if (image.selectionStatus == "unavailable") Text("Review unavailable · showing the available versions", color = Peach, style = MaterialTheme.typography.labelSmall)
            if (image.selectionStatus == "selected") Text(image.selectionReason, color = Slate, style = MaterialTheme.typography.labelSmall)
        }
        state.batch?.targets?.firstOrNull()?.warnings?.forEach { warning -> Text(warning, color = Peach, style = MaterialTheme.typography.labelSmall) }
        Spacer(Modifier.height(11.dp))
        LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            items(results, key = { it.id }) { image ->
                ResultCard(
                    image = image,
                    accentIndex = state.accentIndex(image.connectionId),
                    url = viewModel.imageUrl(image),
                    wide = results.size == 1,
                    onOpen = { selectedId = image.id },
                    onImageReady = { viewModel.imageReady(image) },
                    onReuseSeed = { viewModel.reuseSeed(image) },
                    onSave = { onSaveImage(image) }
                )
            }
        }
    }
    selected?.let { image ->
        ImageViewer(
            image = image,
            accentIndex = state.accentIndex(image.connectionId),
            url = viewModel.imageUrl(image),
            onUseSettings = {
                viewModel.useSettingsFrom(image)
                selectedId = null
            },
            onUseSeed = {
                viewModel.reuseSeed(image)
                selectedId = null
            },
            onSave = { onSaveImage(image) },
            onDismiss = { selectedId = null },
            onImageReady = { viewModel.imageReady(image) },
            onEdit = { selectedId = null; viewModel.editImage(image) }
        )
    }
}

@Composable
private fun ResultCard(
    image: GeneratedImage,
    accentIndex: Int,
    url: String?,
    wide: Boolean,
    onOpen: () -> Unit,
    onImageReady: () -> Unit,
    onReuseSeed: () -> Unit,
    onSave: () -> Unit
) {
    val accent = backendAccent(accentIndex)
    val context = LocalContext.current
    val imageRequest = remember(context, url) {
        // Show a newly decoded result immediately; keep the shared loader's
        // authenticated transport and cache policies unchanged.
        ImageRequest.Builder(context).data(url).crossfade(false).build()
    }
    var imageLoading by remember(image.id, url) { mutableStateOf(url != null) }
    var imageFailed by remember(image.id, url) { mutableStateOf(url == null) }
    var retry by remember(image.id, url) { mutableIntStateOf(0) }
    Column(
        modifier = Modifier
            .width(if (wide) 280.dp else 208.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(Night)
            .border(1.dp, accent.copy(alpha = 0.35f), RoundedCornerShape(16.dp))
            .padding(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(image.aspectRatio)
                .clip(RoundedCornerShape(12.dp))
                .background(PanelRaised)
                .clickable(role = Role.Button, onClickLabel = "Open image", onClick = onOpen)
        ) {
            key(retry) {
                AsyncImage(
                    model = imageRequest,
                    contentDescription = "Image from ${image.connectionName}",
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                    onLoading = {
                        imageLoading = true
                        imageFailed = false
                    },
                    onSuccess = {
                        imageLoading = false
                        imageFailed = false
                        onImageReady()
                    },
                    onError = {
                        imageLoading = false
                        imageFailed = true
                    }
                )
            }
            if (imageLoading || imageFailed) {
                Column(
                    modifier = Modifier.align(Alignment.Center).padding(12.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    if (imageLoading) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp), color = accent)
                        Text("Loading image…", color = Mist, style = MaterialTheme.typography.labelSmall)
                    } else {
                        Text(
                            text = if (url == null) "Reconnect this backend to load the image."
                                else "Could not load the image. Check the backend connection.",
                            color = Mist,
                            style = MaterialTheme.typography.labelSmall,
                            textAlign = TextAlign.Center
                        )
                        if (url != null) {
                            TextButton(onClick = {
                                imageLoading = true
                                imageFailed = false
                                retry += 1
                            }) {
                                Text("Retry image", color = accent)
                            }
                        }
                    }
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            BackendDot(color = accent, size = 7)
            Text(
                text = image.connectionName,
                color = Mist,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Text(text = "Seed ${image.seed}", color = Slate, style = MaterialTheme.typography.labelSmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            QuietButton(label = "Use seed", modifier = Modifier.weight(1f), accent = accent, onClick = onReuseSeed)
            QuietButton(label = "Save", modifier = Modifier.weight(1f), accent = accent, onClick = onSave)
        }
    }
}

@Composable
private fun FailureCard(failures: List<BackendJob>, onRetry: () -> Unit) {
    StudioPanel {
        SectionLabel("Some results need attention")
        Spacer(Modifier.height(10.dp))
        failures.forEach { job ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 5.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                BackendDot(color = Rose, size = 7)
                Text(
                    text = job.connectionName,
                    color = Mist,
                    style = MaterialTheme.typography.titleMedium,
                    maxLines = 1
                )
                Text(
                    text = job.failureReason ?: "Unavailable",
                    color = Slate,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
            }
        }
        Spacer(Modifier.height(10.dp))
        QuietButton(label = "Retry just these", accent = Rose, onClick = onRetry)
        Spacer(Modifier.height(6.dp))
        Text(
            text = "Retries keep the seed each backend was given, so a recovered backend still fills its slot in the set.",
            color = Slate,
            style = MaterialTheme.typography.labelSmall
        )
    }
}
