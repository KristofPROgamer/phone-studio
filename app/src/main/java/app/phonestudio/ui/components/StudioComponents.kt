package app.phonestudio.ui.components

import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Night
import app.phonestudio.ui.theme.Panel
import app.phonestudio.ui.theme.PanelRaised
import app.phonestudio.ui.theme.Peach
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Slate

@Composable
fun StudioPanel(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
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

/** Standard Compose animation follows the system's animator duration scale. */
@Composable
fun DisclosurePanel(
    title: String,
    summary: String,
    modifier: Modifier = Modifier,
    initiallyExpanded: Boolean = false,
    content: @Composable ColumnScope.() -> Unit
) {
    var expanded by rememberSaveable(title) { mutableStateOf(initiallyExpanded) }
    val rotation by animateFloatAsState(
        targetValue = if (expanded) 180f else 0f,
        animationSpec = tween(180),
        label = "Disclosure arrow"
    )
    StudioPanel(modifier.animateContentSize(animationSpec = tween(220))) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .semantics { stateDescription = if (expanded) "Expanded" else "Collapsed" }
                .clickable(
                    role = Role.Button,
                    onClickLabel = if (expanded) "Collapse $title" else "Expand $title"
                ) { expanded = !expanded },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(title, color = Mist, style = MaterialTheme.typography.titleMedium)
                Text(summary, color = Slate, style = MaterialTheme.typography.labelSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            Icon(Icons.Filled.ExpandMore, contentDescription = null, tint = Periwinkle, modifier = Modifier.rotate(rotation))
        }
        if (expanded) {
            Spacer(Modifier.height(14.dp))
            content()
        }
    }
}

/** Optional markers carry counts or live status, rather than decorative steps. */
@Composable
fun SectionLabel(title: String, modifier: Modifier = Modifier, marker: String? = null) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(text = title, color = Periwinkle, style = MaterialTheme.typography.labelMedium)
        if (marker != null) {
            Text(text = marker, color = Peach, style = MaterialTheme.typography.labelMedium)
        }
    }
}

@Composable
fun StudioTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    placeholder: String,
    modifier: Modifier = Modifier,
    minLines: Int = 1,
    password: Boolean = false,
    keyboardOptions: KeyboardOptions = KeyboardOptions.Default,
    trailing: @Composable (() -> Unit)? = null
) {
    var revealed by remember { mutableStateOf(false) }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = {
            Text(placeholder, color = Slate, style = MaterialTheme.typography.bodyMedium)
        },
        minLines = minLines,
        maxLines = if (minLines > 1) 7 else 1,
        visualTransformation = if (password && !revealed) {
            androidx.compose.ui.text.input.PasswordVisualTransformation()
        } else {
            androidx.compose.ui.text.input.VisualTransformation.None
        },
        keyboardOptions = keyboardOptions,
        textStyle = MaterialTheme.typography.bodyMedium.copy(color = Mist),
        shape = RoundedCornerShape(15.dp),
        trailingIcon = when {
            trailing != null -> trailing
            // Pasting a long token on a phone is error-prone; being able to
            // check it without retyping saves a failed connection test.
            password -> {
                {
                    TextButton(onClick = { revealed = !revealed }) {
                        Text(
                            text = if (revealed) "Hide" else "Show",
                            color = Periwinkle,
                            style = MaterialTheme.typography.labelSmall
                        )
                    }
                }
            }
            else -> null
        },
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
fun SelectMenu(
    label: String,
    value: String,
    options: List<String>,
    placeholder: String = "Choose one",
    onChoose: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(text = label, color = Slate, style = MaterialTheme.typography.labelMedium)
        Spacer(Modifier.height(6.dp))
        Box {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .background(Night)
                    .border(1.dp, Slate.copy(alpha = 0.35f), RoundedCornerShape(14.dp))
                    .heightIn(min = 48.dp)
                    .clickable(role = Role.Button) { expanded = true }
                    .padding(horizontal = 13.dp, vertical = 13.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                Text(
                    text = value.ifBlank { placeholder },
                    color = if (value.isBlank()) Slate else Mist,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f)
                )
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
fun ChoiceChip(
    label: String,
    detail: String?,
    selected: Boolean,
    modifier: Modifier = Modifier,
    accent: Color = Periwinkle,
    onClick: () -> Unit
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (selected) accent.copy(alpha = 0.13f) else Night)
            .border(1.dp, if (selected) accent else Slate.copy(alpha = 0.28f), RoundedCornerShape(14.dp))
            .heightIn(min = 48.dp)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 11.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = label,
            color = if (selected) Mist else Slate,
            style = MaterialTheme.typography.titleMedium,
            maxLines = 1
        )
        if (detail != null) {
            Text(
                text = detail,
                color = if (selected) accent else Slate,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 2,
                textAlign = TextAlign.Center
            )
        }
    }
}

@Composable
fun SmallChoice(label: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(12.dp))
            .background(if (selected) Peach else PanelRaised)
            .sizeIn(minWidth = 48.dp, minHeight = 48.dp)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 9.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label,
            color = if (selected) app.phonestudio.ui.theme.Ink else Mist,
            style = MaterialTheme.typography.labelMedium
        )
    }
}

@Composable
fun QuietButton(
    label: String,
    modifier: Modifier = Modifier,
    accent: Color = Periwinkle,
    onClick: () -> Unit
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Night)
            .border(1.dp, accent.copy(alpha = 0.42f), RoundedCornerShape(14.dp))
            .heightIn(min = 48.dp)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(vertical = 12.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label,
            color = accent,
            style = MaterialTheme.typography.labelMedium,
            textAlign = TextAlign.Center
        )
    }
}

@Composable
fun MetricSlider(
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

/** A filled dot in a backend's accent colour, used wherever a backend is named. */
@Composable
fun BackendDot(color: Color, modifier: Modifier = Modifier, size: Int = 9) {
    Box(
        modifier = modifier
            .size(size.dp)
            .clip(CircleShape)
            .background(color)
    )
}

@Composable
fun ThinProgress(progress: Float?, accent: Color, modifier: Modifier = Modifier) {
    if (progress == null) {
        LinearProgressIndicator(
            modifier = modifier
                .fillMaxWidth()
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = accent,
            trackColor = PanelRaised
        )
    } else {
        LinearProgressIndicator(
            progress = { progress },
            modifier = modifier
                .fillMaxWidth()
                .height(3.dp)
                .clip(RoundedCornerShape(2.dp)),
            color = accent,
            trackColor = PanelRaised
        )
    }
}

@Composable
fun EmptyNote(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        color = Slate,
        style = MaterialTheme.typography.bodyMedium,
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(Panel)
            .padding(14.dp)
    )
}

val ScreenPadding = PaddingValues(start = 20.dp, top = 22.dp, end = 20.dp, bottom = 28.dp)
