package app.phonestudio.ui.create

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.Switch
import androidx.compose.ui.Alignment
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import app.phonestudio.data.model.MaskPoint
import app.phonestudio.data.model.MaskStroke
import app.phonestudio.ui.StudioUiState
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.components.*
import app.phonestudio.ui.theme.*
import coil.compose.AsyncImage
import java.io.File

@Composable
fun EditPanel(state: StudioUiState, viewModel: StudioViewModel, onPickImage: () -> Unit) {
    val draft = state.editDraft
    val manual = draft.maskMode == "manual"
    var erase by rememberSaveable { mutableStateOf(false) }
    var current by remember(draft.sourcePath) { mutableStateOf<List<MaskPoint>>(emptyList()) }
    StudioPanel {
        SectionLabel("Edit an image", marker = if (state.isPreparingEdit) "Copying…" else "Draft saved")
        Spacer(Modifier.height(12.dp))
        QuietButton(if (draft.hasSource) "Choose a different image" else "Choose an image", onClick = onPickImage)
        if (draft.sourcePath.isNotBlank()) {
            Spacer(Modifier.height(12.dp))
            Box(Modifier.fillMaxWidth().aspectRatio((if (draft.height > 0) draft.width.toFloat() / draft.height else 1f).coerceIn(0.7f, 2f))) {
                AsyncImage(model = File(draft.sourcePath), contentDescription = "Original edit source", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
                if (manual) Canvas(Modifier.fillMaxSize()
                    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
                    .pointerInput(draft.sourcePath, erase) {
                        fun viewport() = fitMaskViewport(size.width.toFloat(), size.height.toFloat(), draft.width, draft.height)
                        detectDragGestures(
                            onDragStart = { current = listOfNotNull(viewport().normalize(it.x, it.y)) },
                            onDrag = { change, _ ->
                                if (current.isNotEmpty()) {
                                    change.consume()
                                    if (current.size < 2048) viewport().normalize(change.position.x, change.position.y, true)?.let { current = current + it }
                                }
                            },
                            onDragEnd = { if (current.isNotEmpty()) viewModel.addMaskStroke(MaskStroke(current, erase = erase)); current = emptyList() },
                            onDragCancel = { current = emptyList() }
                        )
                    }) {
                    val strokes = draft.strokes + if (current.isEmpty()) emptyList() else listOf(MaskStroke(current, erase = erase))
                    val fitted = fitMaskViewport(size.width, size.height, draft.width, draft.height)
                    clipRect(fitted.left, fitted.top, fitted.left + fitted.width, fitted.top + fitted.height) {
                    strokes.forEach { stroke ->
                        val radius = stroke.radius * minOf(fitted.width, fitted.height)
                        val blend = if (stroke.erase) BlendMode.Clear else BlendMode.SrcOver
                        val color = Color.White.copy(alpha = 0.55f)
                        val points = stroke.points.map { Offset(fitted.left + it.x * fitted.width, fitted.top + it.y * fitted.height) }
                        points.firstOrNull()?.let { drawCircle(color, radius, it, blendMode = blend) }
                        points.zipWithNext().forEach { (a, b) -> drawLine(color, a, b, strokeWidth = radius * 2, cap = StrokeCap.Round, blendMode = blend) }
                    }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ChoiceChip("Automatic area", detail = null, selected = !manual, modifier = Modifier.weight(1f)) {
                    viewModel.updateEdit { it.copy(maskMode = "automatic", strokes = emptyList(), maskPath = "", maskAssetId = null) }
                }
                ChoiceChip("Paint area", detail = null, selected = manual, modifier = Modifier.weight(1f)) { viewModel.updateEdit { it.copy(maskMode = "manual") } }
            }
            if (manual) {
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    QuietButton(if (erase) "Switch to brush" else "Switch to eraser", modifier = Modifier.weight(1f)) { erase = !erase }
                    QuietButton("Undo", modifier = Modifier.weight(1f)) { viewModel.updateEdit { it.copy(strokes = it.strokes.dropLast(1), maskPath = "", maskAssetId = null) } }
                }
            }
            Text(if (manual) "Paint the part to change. Unpainted areas are preserved for local edits."
                else "The assistant finds the area. If it is uncertain, it asks for a painted selection.",
                color = Slate, style = MaterialTheme.typography.labelSmall)
        }
        Spacer(Modifier.height(12.dp))
        StudioTextField(draft.instruction, { value -> viewModel.updateEdit { it.copy(instruction = value) } },
            label = "What should change?", placeholder = "Change the jacket to red; keep the face and background…", minLines = 3)
        Spacer(Modifier.height(10.dp))
        MetricSlider(label = "Preserve the source", value = draft.preservation,
            valueText = "${(draft.preservation * 100).toInt()}%", range = 0f..1f, steps = 0,
            onValueChange = { value -> viewModel.updateEdit { it.copy(preservation = value) } })
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Stronger inpainting", color = Mist, style = MaterialTheme.typography.titleMedium)
                Text("Adds edit guidance when supported. Turn off to compare standard edits.", color = Slate, style = MaterialTheme.typography.labelSmall)
            }
            Switch(checked = state.parameters.auxiliaryInpaint, onCheckedChange = { value -> viewModel.updateParameters { it.copy(auxiliaryInpaint = value) } })
        }
        Text("Higher preservation asks for a gentler edit. Exact identity and intricate edits still depend on the image model. Your source, instructions and settings stay saved when you leave.",
            color = Slate, style = MaterialTheme.typography.labelSmall)
    }
}
