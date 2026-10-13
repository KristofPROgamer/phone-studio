package app.phonestudio.ui.models

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.phonestudio.ui.StudioUiState
import app.phonestudio.ui.StudioViewModel
import app.phonestudio.ui.components.BackendDot
import app.phonestudio.ui.components.DisclosurePanel
import app.phonestudio.ui.components.EmptyNote
import app.phonestudio.ui.components.SectionLabel
import app.phonestudio.ui.components.SmallChoice
import app.phonestudio.ui.components.StudioTextField
import app.phonestudio.ui.theme.Ink
import app.phonestudio.ui.theme.Mint
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Panel
import app.phonestudio.ui.theme.Peach
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Slate
import app.phonestudio.ui.theme.backendAccent

@Composable
fun ModelsScreen(state: StudioUiState, viewModel: StudioViewModel) {
    var civitaiInput by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("checkpoint") }
    var target by rememberSaveable { mutableStateOf<String?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    val search = query.trim()
    val checkpoints = state.catalog.checkpoints.filter { it.contains(search, ignoreCase = true) }
    val loras = state.catalog.loras.filter { it.contains(search, ignoreCase = true) }

    val downloadTargets = state.readyBackends
    val selectedTarget = target
        ?.takeIf { selected -> downloadTargets.any { it.config.id == selected } }
        ?: downloadTargets.firstOrNull()?.config?.id

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item(key = "models-heading") {
            Text(text = "Model shelf", color = Periwinkle, style = MaterialTheme.typography.labelMedium)
            Text(text = "Models", color = Mist, style = MaterialTheme.typography.headlineSmall)
            Text(
                text = "Choose an installed checkpoint or an optional style. Workers without your chosen file are skipped.",
                color = Slate,
                style = MaterialTheme.typography.bodyMedium
            )
        }

        item(key = "model-search") {
            StudioTextField(
                value = query,
                onValueChange = { query = it },
                label = "Search installed models",
                placeholder = "Checkpoint or LoRA name",
                trailing = if (query.isNotEmpty()) {
                    {
                        IconButton(onClick = { query = "" }) {
                            Icon(Icons.Filled.Close, "Clear model search", tint = Periwinkle)
                        }
                    }
                } else null
            )
        }
        item(key = "model-download") {
            DisclosurePanel(
                title = "Add a model",
                summary = state.downloadMessage.takeIf { it.isNotBlank() }
                    ?: "Download a Civitai version to your workers"
            ) {
                StudioTextField(
                    value = civitaiInput,
                    onValueChange = { civitaiInput = it },
                    label = "Model-version URL or ID",
                    placeholder = "…?modelVersionId=123456"
                )
                Spacer(Modifier.height(10.dp))
                Row(modifier = Modifier.selectableGroup(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallChoice("Checkpoint", kind == "checkpoint") { kind = "checkpoint" }
                    SmallChoice("LoRA", kind == "lora") { kind = "lora" }
                }

                if (downloadTargets.size > 1) {
                    Spacer(Modifier.height(12.dp))
                    Text(
                        text = "Download to",
                        color = Slate,
                        style = MaterialTheme.typography.labelMedium
                    )
                    Spacer(Modifier.height(7.dp))
                    Column(modifier = Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        downloadTargets.forEach { card ->
                            val index = state.accentIndex(card.config.id)
                            TargetRow(
                                name = card.config.displayName,
                                accentIndex = index,
                                selected = card.config.id == selectedTarget,
                                onClick = { target = card.config.id }
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "Your router sends the download to its configured image workers.",
                        color = Slate,
                        style = MaterialTheme.typography.labelSmall
                    )
                }

                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = { viewModel.downloadCivitaiModel(civitaiInput, kind, selectedTarget) },
                    enabled = !state.isDownloading && selectedTarget != null && civitaiInput.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                    shape = RoundedCornerShape(15.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Periwinkle, contentColor = Ink)
                ) {
                    if (state.isDownloading) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), color = Ink, strokeWidth = 2.dp)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(
                        text = if (state.isDownloading) "Downloading…" else "Download to workers",
                        style = MaterialTheme.typography.labelMedium
                    )
                }
                if (selectedTarget == null) {
                    Spacer(Modifier.height(8.dp))
                    Text("Connect and enable your router before downloading.", color = Slate, style = MaterialTheme.typography.bodyMedium)
                }
                if (state.downloadMessage.isNotBlank()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = state.downloadMessage,
                        color = if (state.isDownloading) Peach else Slate,
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
        }

        item(key = "checkpoint-heading") {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                SectionLabel(
                    "Checkpoints",
                    modifier = Modifier.weight(1f),
                    marker = if (search.isBlank()) "${checkpoints.size}" else "${checkpoints.size}/${state.catalog.checkpoints.size}"
                )
                TextButton(onClick = viewModel::refreshModels, enabled = !state.isRefreshingModels) {
                    Text(text = if (state.isRefreshingModels) "Refreshing…" else "Refresh", color = if (state.isRefreshingModels) Slate else Periwinkle, style = MaterialTheme.typography.labelMedium)
                }
            }
        }

        if (checkpoints.isEmpty()) {
            item {
                EmptyNote(if (search.isNotBlank()) "No checkpoints match this search." else "No checkpoints found. Refresh the list, download a model, or add a SafeTensors file to MyDrive/PhoneStudio/models/checkpoints.")
            }
        } else {
            items(checkpoints, key = { "checkpoint-$it" }) { model ->
                ShelfRow(
                    name = model,
                    detail = "Checkpoint · ${state.catalog.checkpointAvailability[model]?.size ?: 0} workers",
                    availableOn = state.catalog.checkpointAvailability[model].orEmpty(),
                    accentIndexOf = state::accentIndex,
                    selected = state.parameters.model == model,
                    onClick = { viewModel.chooseModel(model) }
                )
            }
        }

        item(key = "lora-heading") { SectionLabel("Style LoRAs", marker = if (search.isBlank()) "${loras.size}" else "${loras.size}/${state.catalog.loras.size}") }

        if (loras.isEmpty()) {
            item {
                EmptyNote(if (search.isNotBlank()) "No LoRAs match this search." else "No style LoRAs found. They are optional and can be selected in Create → Seed & style.")
            }
        } else {
            items(loras, key = { "lora-$it" }) { lora ->
                ShelfRow(
                    name = lora,
                    detail = "Style LoRA",
                    availableOn = state.catalog.loraAvailability[lora].orEmpty(),
                    accentIndexOf = state::accentIndex,
                    selected = state.parameters.lora == lora,
                    onClick = {
                        viewModel.chooseLora(if (state.parameters.lora == lora) "" else lora)
                    }
                )
            }
        }
    }
}

@Composable
private fun TargetRow(name: String, accentIndex: Int, selected: Boolean, onClick: () -> Unit) {
    val accent = backendAccent(accentIndex)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(if (selected) accent.copy(alpha = 0.12f) else Panel)
            .border(1.dp, if (selected) accent else Slate.copy(alpha = 0.2f), RoundedCornerShape(12.dp))
            .heightIn(min = 48.dp)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        BackendDot(color = accent, size = 8)
        Text(
            text = name,
            color = if (selected) Mist else Slate,
            style = MaterialTheme.typography.titleMedium,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis
        )
    }
}

/**
 * Each row shows which backends hold the file, as accent dots. That is the
 * difference between "this model is missing" and "this model is only on Colab 2",
 * which decides whether a batch will be complete.
 */
@Composable
private fun ShelfRow(
    name: String,
    detail: String,
    availableOn: List<String>,
    accentIndexOf: (String) -> Int,
    selected: Boolean,
    onClick: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(15.dp))
            .background(if (selected) Mint.copy(alpha = 0.10f) else Panel)
            .border(
                1.dp,
                if (selected) Mint else Slate.copy(alpha = 0.18f),
                RoundedCornerShape(15.dp)
            )
            .selectable(selected = selected, role = Role.Button, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = name,
                color = Mist,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(5.dp)
            ) {
                Text(text = detail, color = Slate, style = MaterialTheme.typography.labelSmall)
                availableOn.forEach { id ->
                    BackendDot(color = backendAccent(accentIndexOf(id)), size = 6)
                }
            }
        }
        if (selected) Text(text = "Active", color = Mint, style = MaterialTheme.typography.labelMedium)
    }
}
