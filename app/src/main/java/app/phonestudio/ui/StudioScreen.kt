package app.phonestudio.ui

import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.CloudQueue
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import app.phonestudio.ui.connect.ConnectScreen
import app.phonestudio.ui.create.CreateScreen
import app.phonestudio.ui.create.CreateActionBar
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.ui.library.LibraryScreen
import app.phonestudio.ui.models.ModelsScreen
import app.phonestudio.ui.theme.Ink
import app.phonestudio.ui.theme.Mist
import app.phonestudio.ui.theme.Night
import app.phonestudio.ui.theme.Panel
import app.phonestudio.ui.theme.Periwinkle
import app.phonestudio.ui.theme.Slate

@Composable
fun StudioScreen(
    state: StudioUiState,
    viewModel: StudioViewModel,
    onNotifyChanged: (Boolean) -> Unit,
    onSaveImage: (GeneratedImage) -> Unit,
    onPickImage: () -> Unit
) {
    val snackbarHost = remember { SnackbarHostState() }
    val screenState = rememberSaveableStateHolder()

    LaunchedEffect(state.notice) {
        if (state.notice.isNotBlank()) {
            snackbarHost.showSnackbar(state.notice, duration = SnackbarDuration.Short)
            viewModel.dismissNotice()
        }
    }

    Scaffold(
        modifier = Modifier.imePadding(),
        containerColor = Ink,
        bottomBar = {
            Column(Modifier.navigationBarsPadding().background(Night)) {
                if (state.tab == StudioTab.CREATE) {
                    CreateActionBar(state, viewModel::generate, viewModel::cancelGeneration)
                }
                StudioDock(selected = state.tab, onSelect = viewModel::selectTab)
            }
        },
        snackbarHost = {
            SnackbarHost(snackbarHost) { data ->
                Snackbar(
                    containerColor = Panel,
                    contentColor = Mist,
                    shape = RoundedCornerShape(16.dp),
                    snackbarData = data
                )
            }
        }
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Ink)
                .padding(padding)
                .consumeWindowInsets(padding)
        ) {
            // Compose uses the system animation scale, including disabled animations.
            Crossfade(targetState = state.tab, animationSpec = tween(180), label = "Studio tab") { tab ->
                screenState.SaveableStateProvider(tab.name) {
                    when (tab) {
                        StudioTab.CREATE -> CreateScreen(state, viewModel, onNotifyChanged, onSaveImage, onPickImage)
                        StudioTab.LIBRARY -> LibraryScreen(state, viewModel, onSaveImage)
                        StudioTab.MODELS -> ModelsScreen(state, viewModel)
                        StudioTab.CONNECT -> ConnectScreen(state, viewModel)
                    }
                }
            }
        }
    }
}

@Composable
private fun StudioDock(selected: StudioTab, onSelect: (StudioTab) -> Unit) {
    val items = listOf(
        StudioTab.CREATE to Icons.Filled.AutoAwesome,
        StudioTab.LIBRARY to Icons.Filled.PhotoLibrary,
        StudioTab.MODELS to Icons.Filled.Layers,
        StudioTab.CONNECT to Icons.Filled.CloudQueue
    )
    Surface(color = Night, shadowElevation = 10.dp) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .selectableGroup()
                .padding(horizontal = 10.dp, vertical = 9.dp),
            horizontalArrangement = Arrangement.spacedBy(5.dp)
        ) {
            items.forEach { (tab, icon) ->
                DockItem(
                    tab = tab,
                    icon = icon,
                    selected = selected == tab,
                    modifier = Modifier.weight(1f),
                    onClick = { onSelect(tab) }
                )
            }
        }
    }
}

@Composable
private fun DockItem(
    tab: StudioTab,
    icon: ImageVector,
    selected: Boolean,
    modifier: Modifier,
    onClick: () -> Unit
) {
    val background by animateColorAsState(
        if (selected) Periwinkle.copy(alpha = 0.16f) else Color.Transparent,
        animationSpec = tween(180), label = "Navigation selection"
    )
    val tint by animateColorAsState(
        if (selected) Periwinkle else Slate,
        animationSpec = tween(180), label = "Navigation icon"
    )
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(15.dp))
            .background(background)
            .selectable(selected = selected, role = Role.Tab, onClick = onClick)
            .padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp)
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = tint,
            modifier = Modifier.size(22.dp)
        )
        Text(
            text = tab.label,
            color = if (selected) Mist else Slate,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1
        )
    }
}
