package app.phonestudio.ui.library

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ZoomOutMap
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.ui.StudioUiState
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.StudioTab
import app.phonestudio.ui.components.BackendDot
import app.phonestudio.ui.components.QuietButton
import app.phonestudio.ui.components.SmallChoice
import app.phonestudio.ui.components.StudioTextField
import app.phonestudio.ui.components.EmptyNote
import app.phonestudio.ui.theme.Ink
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Panel
import app.phonestudio.ui.theme.PanelRaised
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Slate
import app.phonestudio.ui.theme.backendAccent
import coil.compose.AsyncImage
import coil.request.ImageRequest
import coil.size.Size
import kotlin.math.min

@Composable
fun LibraryScreen(
    state: StudioUiState,
    viewModel: StudioViewModel,
    onSaveImage: (GeneratedImage) -> Unit
) {
    var selectedId by rememberSaveable { mutableStateOf<String?>(null) }
    val selected = state.library.firstOrNull { it.id == selectedId }
    var confirmClear by rememberSaveable { mutableStateOf(false) }
    var showVersions by rememberSaveable { mutableStateOf(false) }
    var query by rememberSaveable { mutableStateOf("") }
    var imageKind by rememberSaveable { mutableStateOf("all") }
    val visible = remember(state.library, showVersions, query, imageKind) {
        val search = query.trim()
        state.library.filter { image ->
            (showVersions || image.visibleByDefault) &&
                (imageKind == "all" || (image.editInstruction != null) == (imageKind == "edits")) &&
                (search.isBlank() || listOf(image.prompt, image.effectivePrompt, image.model, image.seed.toString(), image.editInstruction.orEmpty())
                    .any { it.contains(search, ignoreCase = true) })
        }
    }

    if (state.library.isEmpty()) {
        EmptyLibrary { viewModel.selectTab(StudioTab.CREATE) }
    } else {
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(20.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item(key = "library-tools", span = { GridItemSpan(2) }) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = "${state.library.size} images saved",
                        color = Periwinkle,
                        style = MaterialTheme.typography.labelMedium
                    )
                    Text(
                        text = "Library",
                        color = Mist,
                        style = MaterialTheme.typography.headlineSmall
                    )
                    Text(
                        text = "Open an image to edit, save or reuse its settings. Every version stays saved.",
                        color = Slate,
                        style = MaterialTheme.typography.bodyMedium
                    )
                    StudioTextField(
                        value = query,
                        onValueChange = { query = it },
                        label = "Search your images",
                        placeholder = "Prompt, model or seed",
                        trailing = if (query.isNotEmpty()) {
                            {
                                IconButton(onClick = { query = "" }) {
                                    Icon(Icons.Filled.Close, "Clear image search", tint = Periwinkle)
                                }
                            }
                        } else null
                    )
                    Row(modifier = Modifier.horizontalScroll(rememberScrollState()).selectableGroup(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                        SmallChoice("All images", imageKind == "all") { imageKind = "all" }
                        SmallChoice("Generated", imageKind == "generated") { imageKind = "generated" }
                        SmallChoice("Edits", imageKind == "edits") { imageKind = "edits" }
                    }
                    if (state.library.any { !it.visibleByDefault }) {
                        Row(modifier = Modifier.horizontalScroll(rememberScrollState()).selectableGroup(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                            SmallChoice("Chosen", !showVersions) { showVersions = false }
                            SmallChoice("All versions", showVersions) { showVersions = true }
                        }
                    }
                    Text("${visible.size} shown", color = Slate, style = MaterialTheme.typography.labelSmall)
                }
            }
            if (visible.isEmpty()) {
                item(key = "no-search-results", span = { GridItemSpan(2) }) {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        EmptyNote("No images match these filters.")
                        QuietButton("Show all images") { query = ""; imageKind = "all"; showVersions = true }
                    }
                }
            }
            items(visible, key = { it.id }) { image ->
                ImageTile(
                    image = image,
                    accentIndex = state.accentIndex(image.connectionId),
                    url = viewModel.imageUrl(image),
                    onClick = { selectedId = image.id }
                )
            }
            item(key = "clear-library", span = { GridItemSpan(2) }) {
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = { confirmClear = true }, modifier = Modifier.fillMaxWidth()) {
                    Text(
                        text = "Clear this list",
                        color = Slate,
                        style = MaterialTheme.typography.labelMedium
                    )
                }
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
            onEdit = { selectedId = null; viewModel.editImage(image) }
        )
    }

    if (confirmClear) {
        AlertDialog(
            onDismissRequest = { confirmClear = false },
            title = { Text("Clear the library list?") },
            text = {
                Text("This removes metadata from the phone only. Images in Google Drive and copies saved to the gallery are not deleted.")
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmClear = false
                        selectedId = null
                        viewModel.clearLibrary()
                    }
                ) { Text("Clear list", color = app.phonestudio.ui.theme.Rose) }
            },
            dismissButton = {
                TextButton(onClick = { confirmClear = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun EmptyLibrary(onCreate: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(text = "◌", color = Periwinkle, fontSize = 54.sp)
        Spacer(Modifier.height(10.dp))
        Text(text = "Your images live here", color = Mist, style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(5.dp))
        Text(
            text = "Create your first image, then return to edit it or reuse its settings.",
            color = Slate,
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(18.dp))
        QuietButton("Create an image", onClick = onCreate)
    }
}

@Composable
private fun ImageTile(
    image: GeneratedImage,
    accentIndex: Int,
    url: String?,
    onClick: () -> Unit
) {
    val accent = backendAccent(accentIndex)
    var thumbnailFailed by remember(image.id, url) { mutableStateOf(url == null) }
    Column(
        modifier = Modifier
            .clip(RoundedCornerShape(17.dp))
            .background(Panel)
            .clickable(role = Role.Button, onClickLabel = "Open image", onClick = onClick)
            .padding(7.dp)
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().aspectRatio(image.aspectRatio)
                .clip(RoundedCornerShape(12.dp)).background(PanelRaised)
        ) {
            AsyncImage(
                model = url,
                contentDescription = "Image from ${image.connectionName}",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
                onSuccess = { thumbnailFailed = false },
                onError = { thumbnailFailed = true }
            )
            if (thumbnailFailed) {
                Text(
                    text = if (url == null) "Reconnect to view" else "Open to retry",
                    modifier = Modifier.align(Alignment.Center).padding(10.dp),
                    color = Mist,
                    style = MaterialTheme.typography.labelSmall,
                    textAlign = TextAlign.Center
                )
            }
        }
        Spacer(Modifier.height(7.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            BackendDot(color = accent, size = 7)
            Text(
                text = image.connectionName,
                color = accent,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        Text(
            text = image.model.substringAfterLast('/'),
            color = Mist,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
        Text(text = "Seed ${image.seed}", color = Slate, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
fun ImageViewer(
    image: GeneratedImage,
    accentIndex: Int,
    url: String?,
    onUseSettings: () -> Unit,
    onUseSeed: () -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit,
    onImageReady: () -> Unit = {},
    onEdit: () -> Unit = {}
) {
    val accent = backendAccent(accentIndex)
    val context = LocalContext.current
    val imageRequest = remember(context, url) {
        // Keep the original pixels available when inspecting a zoomed image.
        ImageRequest.Builder(context).data(url).size(Size.ORIGINAL).build()
    }
    var scale by rememberSaveable(image.id, url) { mutableFloatStateOf(1f) }
    var offset by rememberSaveable(image.id, url, stateSaver = ImageOffsetSaver) { mutableStateOf(Offset.Zero) }
    var imageRatio by remember(image.id, url) { mutableFloatStateOf(image.aspectRatio) }
    var viewport by remember { mutableStateOf(IntSize.Zero) }
    var showInfo by rememberSaveable(image.id) { mutableStateOf(false) }
    var loading by remember(image.id, url) { mutableStateOf(url != null) }
    var failed by remember(image.id, url) { mutableStateOf(url == null) }
    var retry by remember(image.id, url) { mutableIntStateOf(0) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .clipToBounds()
                    .onSizeChanged {
                        viewport = it
                        offset = boundedImageOffset(offset, scale, it, imageRatio)
                    }
                    // Gestures use viewport coordinates, outside the scaled image layer.
                    .pointerInput(image.id, url, viewport, imageRatio) {
                        detectTransformGestures { centroid, pan, zoom, _ ->
                            val previousScale = scale
                            val nextScale = (previousScale * zoom).coerceIn(1f, 5f)
                            val relativeZoom = nextScale / previousScale
                            val center = Offset(viewport.width / 2f, viewport.height / 2f)
                            val anchored = offset * relativeZoom +
                                (centroid - center) * (1f - relativeZoom) + pan
                            offset = boundedImageOffset(anchored, nextScale, viewport, imageRatio)
                            scale = nextScale
                        }
                    }
            ) {
                key(retry) {
                    AsyncImage(
                        model = imageRequest,
                        contentDescription = "Full-screen image from ${image.connectionName}",
                        contentScale = ContentScale.Fit,
                        modifier = Modifier.fillMaxSize().graphicsLayer {
                            scaleX = scale
                            scaleY = scale
                            translationX = offset.x
                            translationY = offset.y
                        },
                        onLoading = { loading = true; failed = false },
                        onSuccess = { success ->
                            loading = false
                            failed = false
                            val drawable = success.result.drawable
                            if (drawable.intrinsicWidth > 0 && drawable.intrinsicHeight > 0) {
                                imageRatio = drawable.intrinsicWidth.toFloat() / drawable.intrinsicHeight
                                offset = boundedImageOffset(offset, scale, viewport, imageRatio)
                            }
                            onImageReady()
                        },
                        onError = { loading = false; failed = true }
                    )
                }
                if (loading || failed) {
                    Column(
                        modifier = Modifier.align(Alignment.Center).padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        if (loading) {
                            CircularProgressIndicator(color = accent, modifier = Modifier.size(28.dp))
                        } else {
                            Text(
                                if (url == null) "Reconnect this backend to load the image."
                                else "Could not load the image. Check the backend connection.",
                                color = Mist,
                                style = MaterialTheme.typography.bodyMedium,
                                textAlign = TextAlign.Center
                            )
                            if (url != null) {
                                TextButton(onClick = { loading = true; failed = false; retry += 1 }) {
                                    Text("Retry image", color = accent)
                                }
                            }
                        }
                    }
                }
            }
            Row(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .safeDrawingPadding()
                    .padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                ViewerIcon(Icons.Filled.Close, "Close image", onDismiss)
                Spacer(Modifier.weight(1f))
                if (scale > 1f) {
                    ViewerIcon(Icons.Filled.ZoomOutMap, "Reset zoom", {
                        scale = 1f
                        offset = Offset.Zero
                    })
                }
                ViewerIcon(Icons.Filled.Download, "Save image to phone", onSave)
                ViewerIcon(Icons.Filled.Edit, "Edit this image", onEdit)
                ViewerIcon(Icons.Filled.Info, "Image information", { showInfo = true }, accent)
            }
            if (showInfo) {
                ImageInformation(image, accent, onUseSettings, onUseSeed, onSave) { showInfo = false }
            }
        }
    }
}

private val ImageOffsetSaver = listSaver<Offset, Float>(
    save = { listOf(it.x, it.y) },
    restore = { Offset(it[0], it[1]) }
)

/** Clamp against the fitted image, including the letterbox space at 1×. */
private fun boundedImageOffset(offset: Offset, scale: Float, viewport: IntSize, aspectRatio: Float): Offset {
    if (scale <= 1f || viewport.width == 0 || viewport.height == 0) return Offset.Zero
    val ratio = aspectRatio.takeIf { it.isFinite() && it > 0f } ?: 1f
    val fittedWidth = min(viewport.width.toFloat(), viewport.height * ratio)
    val fittedHeight = fittedWidth / ratio
    val maxX = ((fittedWidth * scale - viewport.width) / 2f).coerceAtLeast(0f)
    val maxY = ((fittedHeight * scale - viewport.height) / 2f).coerceAtLeast(0f)
    return Offset(offset.x.coerceIn(-maxX, maxX), offset.y.coerceIn(-maxY, maxY))
}

@Composable
private fun ViewerIcon(icon: ImageVector, label: String, onClick: () -> Unit, color: Color = Mist) {
    IconButton(
        onClick = onClick,
        modifier = Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)).background(Ink.copy(alpha = 0.78f))
    ) {
        Icon(icon, contentDescription = label, tint = color)
    }
}

@Composable
private fun ImageInformation(
    image: GeneratedImage,
    accent: Color,
    onUseSettings: () -> Unit,
    onUseSeed: () -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit
) {
    val maxHeight = LocalConfiguration.current.screenHeightDp.dp * 0.85f
    val clipboard = LocalClipboardManager.current
    var promptCopied by rememberSaveable(image.id) { mutableStateOf(false) }
    Dialog(onDismissRequest = onDismiss) {
        Surface(color = Panel, shape = RoundedCornerShape(22.dp)) {
            Column(
                modifier = Modifier.fillMaxWidth().heightIn(max = maxHeight).padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "Image information",
                        color = Mist,
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f)
                    )
                    IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                        Icon(Icons.Filled.Close, contentDescription = "Close image information", tint = Mist)
                    }
                }
                Column(
                    modifier = Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    DetailLine("Backend", image.connectionName)
                    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("Prompt", color = accent, style = MaterialTheme.typography.labelMedium, modifier = Modifier.weight(1f))
                        TextButton(onClick = { clipboard.setText(AnnotatedString(image.prompt)); promptCopied = true }) {
                            Text(if (promptCopied) "Copied" else "Copy prompt", color = accent)
                        }
                    }
                    SelectionContainer { Text(image.prompt, color = Mist, style = MaterialTheme.typography.bodyMedium) }
                    if (image.effectivePrompt.isNotBlank() && image.effectivePrompt != image.prompt) {
                        Text("Effective tags", color = accent, style = MaterialTheme.typography.labelMedium)
                        Text(image.effectivePrompt, color = Mist, style = MaterialTheme.typography.bodyMedium)
                    }
                    image.editInstruction?.let { DetailLine("Edit", it) }
                    image.editMode?.let { DetailLine("Edit mode", it) }
                    if (image.editInstruction != null) {
                        DetailLine("Inpaint", if (image.fooocusInpaint) "Fooocus edit guidance" else "Standard editing")
                        if (image.workingWidth > 0) DetailLine("Working size", "${image.workingWidth} × ${image.workingHeight}")
                    }
                    if (image.routerAssetId != null) {
                        DetailLine("Review", image.selectionStatus)
                        if (image.selectionReason.isNotBlank()) DetailLine("Choice", image.selectionReason)
                        if (image.reviewerModel.isNotBlank()) DetailLine("Reviewer", image.reviewerModel)
                        if (image.reviewerRevision.isNotBlank()) DetailLine("Revision", image.reviewerRevision)
                        image.reviewScore?.let { DetailLine("Scores /10", "Prompt ${it.adherence} · preservation ${it.preservation} · detail ${it.quality}") }
                        DetailLine("Version", if (image.selected) "Selected" else "Alternative")
                    }
                    if (image.negativePrompt.isNotBlank() || image.negativePromptRecorded) {
                        Text("Negative prompt", color = accent, style = MaterialTheme.typography.labelMedium)
                        Text(image.negativePrompt.ifBlank { "None" }, color = Mist, style = MaterialTheme.typography.bodyMedium)
                    }
                    DetailLine("Model", image.model)
                    DetailLine("Size", "${image.width} × ${image.height}")
                    DetailLine("Seed", image.seed.toString())
                    if (image.steps > 0) {
                        DetailLine("Sampling", "${image.sampler}/${image.scheduler} · ${image.steps} steps")
                    }
                    if (image.cfg > 0f) DetailLine("Guidance", image.cfg.toString())
                    DetailLine("Extras", if (image.speedExtras) "On" else "Off")
                    if (image.lora.isNotBlank()) {
                        DetailLine("LoRA", image.lora)
                        DetailLine("Weight", image.loraStrength?.takeIf { it.isFinite() }?.toString() ?: "Not recorded")
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    QuietButton("Use seed", modifier = Modifier.weight(1f), accent = accent, onClick = onUseSeed)
                    QuietButton("Use settings", modifier = Modifier.weight(1f), accent = accent, onClick = onUseSettings)
                }
                QuietButton("Save to phone", modifier = Modifier.fillMaxWidth(), accent = accent, onClick = onSave)
            }
        }
    }
}

@Composable
private fun DetailLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            text = label,
            color = Slate,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.width(72.dp)
        )
        Text(
            text = value,
            color = Mist,
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.weight(1f)
        )
    }
}
