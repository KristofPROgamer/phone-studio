package app.phonestudio.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import app.phonestudio.StudioViewModel
import app.phonestudio.data.ConnectionConfig
import app.phonestudio.data.ConnectionStatus
import app.phonestudio.data.GeneratedImage
import app.phonestudio.data.GenerationParameters
import app.phonestudio.data.StudioTab
import app.phonestudio.data.StudioUiState
import coil.compose.AsyncImage
import coil.request.ImageRequest
import okhttp3.Credentials

@Composable
fun PhoneStudioApp(state: StudioUiState, viewModel: StudioViewModel) {
    Scaffold(
        containerColor = Ink,
        bottomBar = {
            StudioDock(selected = state.tab, onSelect = viewModel::selectTab)
        }
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Ink)
                .padding(padding)
        ) {
            when (state.tab) {
                StudioTab.CREATE -> CreateScreen(state, viewModel)
                StudioTab.LIBRARY -> LibraryScreen(state)
                StudioTab.MODELS -> ModelsScreen(state, viewModel)
                StudioTab.CONNECT -> ConnectScreen(state, viewModel)
            }
        }
    }
}

@Composable
private fun StudioDock(selected: StudioTab, onSelect: (StudioTab) -> Unit) {
    val tabs = listOf(
        StudioTab.CREATE to "Create",
        StudioTab.LIBRARY to "Library",
        StudioTab.MODELS to "Models",
        StudioTab.CONNECT to "Connect"
    )
    Surface(color = Night, shadowElevation = 10.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            tabs.forEach { (tab, label) ->
                val isSelected = selected == tab
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(15.dp))
                        .background(if (isSelected) Periwinkle.copy(alpha = 0.16f) else Color.Transparent)
                        .clickable { onSelect(tab) }
                        .padding(vertical = 8.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        text = if (isSelected) "●" else "·",
                        color = if (isSelected) Peach else Slate,
                        fontSize = 15.sp,
                        lineHeight = 13.sp
                    )
                    Text(
                        text = label.uppercase(),
                        color = if (isSelected) Mist else Slate,
                        style = MaterialTheme.typography.labelMedium,
                        maxLines = 1
                    )
                }
            }
        }
    }
}

@Composable
private fun CreateScreen(state: StudioUiState, viewModel: StudioViewModel) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 20.dp, top = 22.dp, end = 20.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item { StudioMasthead(subtitle = "A quiet control desk for your Colab GPU") }
        item {
            ConnectionRibbon(
                status = state.connectionStatus,
                message = state.connectionMessage,
                onClick = { viewModel.selectTab(StudioTab.CONNECT) }
            )
        }
        item {
            PromptCard(
                params = state.parameters,
                onChange = { viewModel.updateParameters { _ -> it } }
            )
        }
        item {
            ModelCard(
                params = state.parameters,
                checkpoints = state.catalog.checkpoints,
                onChoose = viewModel::chooseModel,
                onOpenModels = { viewModel.selectTab(StudioTab.MODELS) }
            )
        }
        item {
            FormatCard(
                params = state.parameters,
                onChange = { viewModel.updateParameters { _ -> it } }
            )
        }
        item {
            RenderPaceCard(
                params = state.parameters,
                onChange = { viewModel.updateParameters { _ -> it } }
            )
        }
        item {
            AdvancedCard(
                params = state.parameters,
                loras = state.catalog.loras,
                onChange = { viewModel.updateParameters { _ -> it } }
            )
        }
        item {
            GenerateButton(
                busy = state.isGenerating,
                message = state.generationMessage,
                notifyOnCompletion = state.notifyOnCompletion,
                onNotifyChanged = viewModel::setNotifyOnCompletion,
                onGenerate = viewModel::generate
            )
        }
        state.images.firstOrNull()?.let { image ->
            item { LatestImageCard(image = image, config = state.config) }
        }
    }
}

@Composable
private fun StudioMasthead(subtitle: String) {
    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(
            text = "PHONE STUDIO",
            color = Periwinkle,
            style = MaterialTheme.typography.labelMedium
        )
        Text(
            text = "Make an image.\nKeep the knobs quiet.",
            color = Mist,
            style = MaterialTheme.typography.displaySmall,
            lineHeight = 35.sp
        )
        Text(text = subtitle, color = Slate, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun ConnectionRibbon(status: ConnectionStatus, message: String, onClick: () -> Unit) {
    val accent = when (status) {
        ConnectionStatus.CONNECTED -> Mint
        ConnectionStatus.CONNECTING -> Peach
        ConnectionStatus.ERROR -> Rose
        ConnectionStatus.IDLE -> Slate
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(17.dp))
            .background(Panel)
            .border(1.dp, accent.copy(alpha = 0.26f), RoundedCornerShape(17.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 15.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Box(
            modifier = Modifier
                .size(9.dp)
                .clip(RoundedCornerShape(5.dp))
                .background(accent)
        )
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = when (status) {
                    ConnectionStatus.CONNECTED -> "COLAB ONLINE"
                    ConnectionStatus.CONNECTING -> "CHECKING COLAB"
                    ConnectionStatus.ERROR -> "CONNECTION NEEDS ATTENTION"
                    ConnectionStatus.IDLE -> "COLAB NOT CONNECTED"
                },
                color = accent,
                style = MaterialTheme.typography.labelMedium
            )
            Text(text = message, color = Mist, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Text(text = "EDIT", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun PromptCard(params: GenerationParameters, onChange: (GenerationParameters) -> Unit) {
    var showNegative by rememberSaveable { mutableStateOf(false) }
    StudioPanel {
        SectionLabel("THE SCENE", "01")
        Spacer(Modifier.height(9.dp))
        ExposureRail()
        Spacer(Modifier.height(12.dp))
        StudioTextField(
            value = params.prompt,
            onValueChange = { onChange(params.copy(prompt = it)) },
            label = "Describe the image",
            placeholder = "A midnight greenhouse drifting through a city of clouds…",
            minLines = 4
        )
        TextButton(onClick = { showNegative = !showNegative }, contentPadding = PaddingValues(top = 7.dp, bottom = 0.dp)) {
            Text(
                text = if (showNegative) "− HIDE NEGATIVE PROMPT" else "+ ADD NEGATIVE PROMPT",
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
    }
}

@Composable
private fun ExposureRail() {
    val bars = listOf(8, 13, 18, 11, 23, 30, 17, 26, 12, 20, 8)
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.Bottom
    ) {
        bars.forEachIndexed { index, height ->
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(height.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(
                        if (index in 4..7) Peach.copy(alpha = 0.78f) else Periwinkle.copy(alpha = 0.38f)
                    )
            )
        }
    }
}

@Composable
private fun ModelCard(
    params: GenerationParameters,
    checkpoints: List<String>,
    onChoose: (String) -> Unit,
    onOpenModels: () -> Unit
) {
    StudioPanel {
        SectionLabel("THE LENS", "02")
        Spacer(Modifier.height(11.dp))
        if (checkpoints.isEmpty()) {
            Text(text = "No checkpoints are visible yet.", color = Mist, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(text = "Add one from Civitai or place a SafeTensors checkpoint in Drive, then refresh.", color = Slate, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(10.dp))
            QuietButton(label = "OPEN MODELS", onClick = onOpenModels)
        } else {
            SelectMenu(
                label = "Checkpoint",
                value = params.model,
                options = checkpoints,
                onChoose = onChoose
            )
        }
    }
}

@Composable
private fun FormatCard(params: GenerationParameters, onChange: (GenerationParameters) -> Unit) {
    StudioPanel {
        SectionLabel("THE LATENT CANVAS", "03")
        Spacer(Modifier.height(11.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            FormatChip("Tall", "768 × 1024", params.width == 768 && params.height == 1024, Modifier.weight(1f)) {
                onChange(params.copy(width = 768, height = 1024))
            }
            FormatChip("Square", "1024 × 1024", params.width == 1024 && params.height == 1024, Modifier.weight(1f)) {
                onChange(params.copy(width = 1024, height = 1024))
            }
            FormatChip("Wide", "1024 × 768", params.width == 1024 && params.height == 768, Modifier.weight(1f)) {
                onChange(params.copy(width = 1024, height = 768))
            }
        }
        Spacer(Modifier.height(10.dp))
        Text(
            text = "The app uses an Empty Latent Image node with this exact size.",
            color = Slate,
            style = MaterialTheme.typography.bodyMedium
        )
    }
}

@Composable
private fun FormatChip(label: String, size: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val border = if (selected) Periwinkle else Slate.copy(alpha = 0.28f)
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (selected) Periwinkle.copy(alpha = 0.13f) else Night)
            .border(1.dp, border, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 11.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = label, color = if (selected) Mist else Slate, style = MaterialTheme.typography.titleMedium)
        Text(text = size, color = if (selected) Periwinkle else Slate, style = MaterialTheme.typography.labelMedium, maxLines = 1)
    }
}

@Composable
private fun RenderPaceCard(params: GenerationParameters, onChange: (GenerationParameters) -> Unit) {
    StudioPanel {
        SectionLabel("RENDER PACE", "04")
        Spacer(Modifier.height(11.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
            FormatChip("Fast", "18 steps", params.steps == 18, Modifier.weight(1f)) {
                onChange(params.copy(steps = 18))
            }
            FormatChip("Balanced", "28 steps", params.steps == 28, Modifier.weight(1f)) {
                onChange(params.copy(steps = 28))
            }
        }
        Spacer(Modifier.height(10.dp))
        val detail = when (params.steps) {
            18 -> "Faster drafts with fewer diffusion steps."
            28 -> "Balanced quality is the current default."
            else -> "Custom: ${params.steps} steps. Choose a pace to reset it."
        }
        Text(text = detail, color = Slate, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun AdvancedCard(params: GenerationParameters, loras: List<String>, onChange: (GenerationParameters) -> Unit) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    StudioPanel(modifier = Modifier.animateContentSize()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
            ) {
            Column {
                SectionLabel("FINE EXPOSURE", "05")
                Text(text = "Steps, CFG, seed, and optional LoRA", color = Slate, style = MaterialTheme.typography.bodyMedium)
            }
            Text(text = if (expanded) "−" else "+", color = Periwinkle, fontSize = 26.sp)
        }
        if (expanded) {
            Spacer(Modifier.height(14.dp))
            MetricSlider(
                label = "STEPS",
                valueText = params.steps.toString(),
                value = params.steps.toFloat(),
                range = 12f..50f,
                steps = 37,
                onValueChange = { onChange(params.copy(steps = it.toInt())) }
            )
            Spacer(Modifier.height(11.dp))
            MetricSlider(
                label = "CFG",
                valueText = String.format("%.1f", params.cfg),
                value = params.cfg,
                range = 1f..12f,
                steps = 21,
                onValueChange = { onChange(params.copy(cfg = (it * 10).toInt() / 10f)) }
            )
            Spacer(Modifier.height(13.dp))
            StudioTextField(
                value = if (params.seed < 0) "" else params.seed.toString(),
                onValueChange = { raw -> onChange(params.copy(seed = raw.toLongOrNull() ?: -1L)) },
                label = "Seed",
                placeholder = "Random every time",
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
            )
            if (loras.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                SelectMenu(
                    label = "LoRA (optional)",
                    value = params.lora.ifBlank { "None" },
                    options = listOf("None") + loras,
                    onChoose = { selection -> onChange(params.copy(lora = if (selection == "None") "" else selection)) }
                )
                if (params.lora.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    MetricSlider(
                        label = "LORA WEIGHT",
                        valueText = String.format("%.2f", params.loraStrength),
                        value = params.loraStrength,
                        range = 0f..1.5f,
                        steps = 14,
                        onValueChange = { onChange(params.copy(loraStrength = (it * 100).toInt() / 100f)) }
                    )
                }
            }
        }
    }
}

@Composable
private fun MetricSlider(
    label: String,
    valueText: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    steps: Int,
    onValueChange: (Float) -> Unit
) {
    Column {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(text = label, color = Slate, style = MaterialTheme.typography.labelMedium)
            Text(text = valueText, color = Peach, style = MaterialTheme.typography.labelMedium)
        }
        Slider(
            value = value,
            onValueChange = onValueChange,
            valueRange = range,
            steps = steps,
            colors = SliderDefaults.colors(
                thumbColor = Peach,
                activeTrackColor = Periwinkle,
                inactiveTrackColor = PanelRaised
            )
        )
    }
}

@Composable
private fun GenerateButton(
    busy: Boolean,
    message: String,
    notifyOnCompletion: Boolean,
    onNotifyChanged: (Boolean) -> Unit,
    onGenerate: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            onClick = onGenerate,
            enabled = !busy,
            shape = RoundedCornerShape(20.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Peach, contentColor = Ink)
        ) {
            if (busy) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), color = Ink, strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text(text = "RENDERING", style = MaterialTheme.typography.labelMedium)
            } else {
                Text(text = "GENERATE IMAGE", style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.width(8.dp))
                Text(text = "↗", fontSize = 20.sp, fontWeight = FontWeight.Bold)
            }
        }
        if (message.isNotBlank()) {
            Text(
                text = message,
                color = if (busy) Peach else Slate,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(Panel)
                .padding(horizontal = 13.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(text = "NOTIFY WHEN READY", color = Mist, style = MaterialTheme.typography.labelMedium)
                Text(
                    text = "Get an alert if the render completes while you are away.",
                    color = Slate,
                    style = MaterialTheme.typography.bodyMedium
                )
            }
            Switch(checked = notifyOnCompletion, onCheckedChange = onNotifyChanged)
        }
    }
}

@Composable
private fun LatestImageCard(image: GeneratedImage, config: ConnectionConfig) {
    StudioPanel {
        SectionLabel("JUST DEVELOPED", "OUTPUT")
        Spacer(Modifier.height(10.dp))
        AsyncImage(
            model = securedImageRequest(image.url, config),
            contentDescription = "Generated image",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(image.width.toFloat() / image.height)
                .clip(RoundedCornerShape(16.dp))
                .background(PanelRaised)
        )
        Spacer(Modifier.height(10.dp))
        Text(text = image.prompt, color = Mist, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
        Text(text = "${image.model}  ·  seed ${image.seed}", color = Slate, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun LibraryScreen(state: StudioUiState) {
    var selectedImage by remember { mutableStateOf<GeneratedImage?>(null) }
    if (state.images.isEmpty()) {
        EmptyLibrary()
    } else {
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item(span = { androidx.compose.foundation.lazy.grid.GridItemSpan(2) }) {
                Column {
                    Text(text = "YOUR CONTACT SHEET", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
                    Text(text = "Session library", color = Mist, style = MaterialTheme.typography.headlineSmall)
                    Text(text = "Images are saved in Google Drive by ComfyUI and kept here for this phone session.", color = Slate, style = MaterialTheme.typography.bodyMedium)
                }
            }
            items(state.images, key = { it.id }) { image ->
                ImageTile(image = image, config = state.config, onClick = { selectedImage = image })
            }
        }
    }
    selectedImage?.let { image -> ImageDetail(image = image, config = state.config, onDismiss = { selectedImage = null }) }
}

@Composable
private fun EmptyLibrary() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = "◌", color = Periwinkle, fontSize = 54.sp)
        Spacer(Modifier.height(10.dp))
        Text(text = "Nothing developed yet.", color = Mist, style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(5.dp))
        Text(text = "Your next generated image will appear here and in your Drive output folder.", color = Slate, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
    }
}

@Composable
private fun ImageTile(image: GeneratedImage, config: ConnectionConfig, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(17.dp))
            .background(Panel)
            .clickable(onClick = onClick)
            .padding(7.dp)
    ) {
        AsyncImage(
            model = securedImageRequest(image.url, config),
            contentDescription = "Generated image",
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(0.84f)
                .clip(RoundedCornerShape(12.dp))
                .background(PanelRaised)
        )
        Spacer(Modifier.height(7.dp))
        Text(text = image.model, color = Periwinkle, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(text = "seed ${image.seed}", color = Slate, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun ImageDetail(image: GeneratedImage, config: ConnectionConfig, onDismiss: () -> Unit) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {
            AsyncImage(
                model = securedImageRequest(image.url, config),
                contentDescription = "Full-screen generated image",
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxSize()
                    .clickable(onClick = onDismiss)
            )
            Text(
                text = "CLOSE",
                color = Mist,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(18.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(Ink.copy(alpha = 0.78f))
                    .clickable(onClick = onDismiss)
                    .padding(horizontal = 13.dp, vertical = 10.dp)
            )
            Column(
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .fillMaxWidth()
                    .background(
                        Brush.verticalGradient(
                            colors = listOf(Color.Transparent, Ink.copy(alpha = 0.96f))
                        )
                    )
                    .padding(start = 22.dp, top = 48.dp, end = 22.dp, bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                Text(text = image.prompt, color = Mist, style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis)
                Text(text = "${image.model} · ${image.width}×${image.height} · seed ${image.seed}", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
                Text(text = "TAP IMAGE TO CLOSE", color = Slate, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun ModelsScreen(state: StudioUiState, viewModel: StudioViewModel) {
    var civitaiInput by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("checkpoint") }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Text(text = "MODEL SHELF", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
            Text(text = "Bring your own lens.", color = Mist, style = MaterialTheme.typography.headlineSmall)
            Text(text = "Civitai files download into your Drive-backed ComfyUI folders, not your phone.", color = Slate, style = MaterialTheme.typography.bodyMedium)
        }
        item {
            StudioPanel {
                SectionLabel("CIVITAI DELIVERY", "DRIVE")
                Spacer(Modifier.height(10.dp))
                StudioTextField(
                    value = civitaiInput,
                    onValueChange = { civitaiInput = it },
                    label = "Civitai model-version URL or ID",
                    placeholder = "…?modelVersionId=123456",
                    minLines = 1
                )
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallChoice("Checkpoint", kind == "checkpoint") { kind = "checkpoint" }
                    SmallChoice("LoRA", kind == "lora") { kind = "lora" }
                }
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = { viewModel.downloadCivitaiModel(civitaiInput, kind) },
                    enabled = !state.isDownloading,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(15.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Periwinkle, contentColor = Ink)
                ) {
                    if (state.isDownloading) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Ink, strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(text = if (state.isDownloading) "DOWNLOADING TO DRIVE" else "DOWNLOAD TO COLAB", style = MaterialTheme.typography.labelMedium)
                }
                if (state.downloadMessage.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Text(text = state.downloadMessage, color = if (state.isDownloading) Peach else Slate, style = MaterialTheme.typography.bodyMedium)
                }
                Spacer(Modifier.height(6.dp))
                Text(text = "Use the model-version ID, not only the broad Civitai model page. LoRAs can be selected from Fine Exposure once downloaded.", color = Slate.copy(alpha = 0.82f), style = MaterialTheme.typography.bodyMedium)
            }
        }
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                SectionLabel("CHECKPOINTS", "${state.catalog.checkpoints.size}")
                TextButton(onClick = viewModel::refreshModels) {
                    Text(text = "REFRESH", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
                }
            }
        }
        if (state.catalog.checkpoints.isEmpty()) {
            item { EmptyModelNote("No checkpoints found. Download one above, or add a SafeTensors file to MyDrive/PhoneStudio/models/checkpoints.") }
        } else {
            items(state.catalog.checkpoints, key = { "checkpoint-$it" }) { model ->
                ShelfRow(
                    name = model,
                    selected = state.parameters.model == model,
                    detail = "Checkpoint",
                    onClick = { viewModel.chooseModel(model) }
                )
            }
        }
        item { SectionLabel("LORAS", "${state.catalog.loras.size}") }
        if (state.catalog.loras.isEmpty()) {
            item { EmptyModelNote("No LoRAs found. They are optional and are mixed into a selected checkpoint from Fine Exposure.") }
        } else {
            items(state.catalog.loras, key = { "lora-$it" }) { lora ->
                ShelfRow(
                    name = lora,
                    selected = state.parameters.lora == lora,
                    detail = "LoRA",
                    onClick = { viewModel.updateParameters { params -> params.copy(lora = if (params.lora == lora) "" else lora) } }
                )
            }
        }
    }
}

@Composable
private fun SmallChoice(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        text = label.uppercase(),
        color = if (selected) Ink else Slate,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier
            .clip(RoundedCornerShape(12.dp))
            .background(if (selected) Peach else PanelRaised)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 9.dp)
    )
}

@Composable
private fun EmptyModelNote(text: String) {
    Text(
        text = text,
        color = Slate,
        style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier
            .clip(RoundedCornerShape(14.dp))
            .background(Panel)
            .padding(14.dp)
    )
}

@Composable
private fun ShelfRow(name: String, selected: Boolean, detail: String, onClick: () -> Unit) {
    val borderColor = if (selected) Mint else Slate.copy(alpha = 0.18f)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(15.dp))
            .background(if (selected) Mint.copy(alpha = 0.10f) else Panel)
            .border(1.dp, borderColor, RoundedCornerShape(15.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        Text(text = if (selected) "●" else "○", color = if (selected) Mint else Slate, fontSize = 16.sp)
        Column(modifier = Modifier.weight(1f)) {
            Text(text = name, color = Mist, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(text = detail.uppercase(), color = Slate, style = MaterialTheme.typography.labelMedium)
        }
        if (selected) Text(text = "ACTIVE", color = Mint, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun ConnectScreen(state: StudioUiState, viewModel: StudioViewModel) {
    val context = LocalContext.current
    var draft by remember(state.config) { mutableStateOf(state.config) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Text(text = "CONNECTION DESK", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
            Text(text = "Your private bridge to Colab.", color = Mist, style = MaterialTheme.typography.headlineSmall)
            Text(text = "Colab allocates GPU sessions in its own browser UI. Phone Studio can open your saved notebook, then connects once its final cell prints a tunnel URL.", color = Slate, style = MaterialTheme.typography.bodyMedium)
        }
        item {
            StudioPanel {
                SectionLabel("START THE GPU", "STEP 1")
                Spacer(Modifier.height(7.dp))
                Text(text = "Save a shareable Colab link here once. Opening it lets you choose T4 and run the notebook; the phone app never receives your Google login.", color = Slate, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(11.dp))
                StudioTextField(
                    value = draft.colabUrl,
                    onValueChange = { draft = draft.copy(colabUrl = it) },
                    label = "Your Colab notebook URL",
                    placeholder = "https://colab.research.google.com/…"
                )
                Spacer(Modifier.height(10.dp))
                QuietButton(label = "OPEN COLAB", onClick = {
                    val destination = draft.colabUrl.ifBlank { "https://colab.research.google.com/" }
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(destination)))
                })
            }
        }
        item {
            StudioPanel {
                SectionLabel("PASTE THE FINAL CELL", "STEP 2")
                Spacer(Modifier.height(11.dp))
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
                    placeholder = "From Colab",
                    password = true
                )
                Spacer(Modifier.height(10.dp))
                StudioTextField(
                    value = draft.studioToken,
                    onValueChange = { draft = draft.copy(studioToken = it) },
                    label = "Phone Studio token",
                    placeholder = "From Colab",
                    password = true
                )
                Spacer(Modifier.height(14.dp))
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = {
                        viewModel.saveConnection(draft)
                        viewModel.connect()
                    },
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Periwinkle, contentColor = Ink)
                ) {
                    if (state.connectionStatus == ConnectionStatus.CONNECTING) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Ink, strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(text = if (state.connectionStatus == ConnectionStatus.CONNECTING) "TESTING CONNECTION" else "SAVE & TEST CONNECTION", style = MaterialTheme.typography.labelMedium)
                }
                Spacer(Modifier.height(9.dp))
                ConnectionRibbon(status = state.connectionStatus, message = state.connectionMessage, onClick = viewModel::connect)
            }
        }
        item {
            TextButton(onClick = viewModel::forgetConnection, modifier = Modifier.fillMaxWidth()) {
                Text(text = "FORGET CONNECTION ON THIS PHONE", color = Rose, style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

@Composable
private fun StudioPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(Panel)
            .border(1.dp, Color.White.copy(alpha = 0.055f), RoundedCornerShape(22.dp))
            .padding(16.dp),
        content = content
    )
}

@Composable
private fun SectionLabel(title: String, number: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(text = title, color = Periwinkle, style = MaterialTheme.typography.labelMedium)
        Text(text = number, color = Peach, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
private fun StudioTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
    minLines: Int = 1,
    password: Boolean = false,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = { Text(placeholder, color = Slate.copy(alpha = 0.72f), style = MaterialTheme.typography.bodyMedium) },
        minLines = minLines,
        maxLines = if (minLines > 1) 7 else 1,
        visualTransformation = if (password) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = keyboardOptions,
        textStyle = MaterialTheme.typography.bodyMedium.copy(color = Mist),
        shape = RoundedCornerShape(15.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Periwinkle,
            unfocusedBorderColor = Slate.copy(alpha = 0.35f),
            focusedLabelColor = Periwinkle,
            unfocusedLabelColor = Slate,
            cursorColor = Peach,
            focusedContainerColor = Night.copy(alpha = 0.62f),
            unfocusedContainerColor = Night.copy(alpha = 0.40f)
        )
    )
}

@Composable
private fun SelectMenu(label: String, value: String, options: List<String>, onChoose: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(text = label.uppercase(), color = Slate, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(6.dp))
        Box {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(Night)
                    .border(1.dp, Slate.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
                    .clickable { expanded = true }
                    .padding(horizontal = 13.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(text = value.ifBlank { "Choose a model" }, color = if (value.isBlank()) Slate else Mist, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Text(text = "⌄", color = Periwinkle, fontSize = 18.sp)
            }
            DropdownMenu(
                expanded = expanded,
                onDismissRequest = { expanded = false },
                modifier = Modifier
                    .background(PanelRaised)
                    .widthIn(max = 340.dp)
            ) {
                options.forEach { option ->
                    DropdownMenuItem(
                        text = { Text(option, maxLines = 2, overflow = TextOverflow.Ellipsis) },
                        onClick = {
                            onChoose(option)
                            expanded = false
                        }
                    )
                }
            }
        }
    }
}

@Composable
private fun QuietButton(label: String, onClick: () -> Unit) {
    Text(
        text = label,
        color = Periwinkle,
        style = MaterialTheme.typography.labelMedium,
        textAlign = TextAlign.Center,
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Night)
            .border(1.dp, Periwinkle.copy(alpha = 0.42f), RoundedCornerShape(14.dp))
            .clickable(onClick = onClick)
            .padding(vertical = 12.dp)
    )
}

@Composable
private fun securedImageRequest(url: String, config: ConnectionConfig): ImageRequest {
    val context = LocalContext.current
    return remember(url, config.serverUrl, config.tunnelUser, config.tunnelPassword) {
        ImageRequest.Builder(context)
            .data(url)
            .addHeader("ngrok-skip-browser-warning", "1")
            .apply {
                if (config.tunnelUser.isNotBlank() && config.tunnelPassword.isNotBlank()) {
                    addHeader("Authorization", Credentials.basic(config.tunnelUser, config.tunnelPassword))
                }
            }
            .crossfade(true)
            .build()
    }
}
