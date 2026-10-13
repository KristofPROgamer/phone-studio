package app.phonestudio.ui

import app.phonestudio.data.model.ConnectionConfig
import app.phonestudio.data.model.ConnectionStatus
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.GenerationBatch
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.ModelCatalog
import app.phonestudio.data.model.EditDraft
import app.phonestudio.data.model.RouterWorker

enum class StudioTab(val label: String) {
    CREATE("Create"),
    LIBRARY("Library"),
    MODELS("Models"),
    CONNECT("Connect")
}

/** A saved backend plus whatever the app last learned about it. */
data class BackendCard(
    val config: ConnectionConfig,
    val status: ConnectionStatus = ConnectionStatus(),
    val catalog: ModelCatalog = ModelCatalog()
)

data class StudioUiState(
    val tab: StudioTab = StudioTab.CREATE,
    val backends: List<BackendCard> = emptyList(),
    val parameters: GenerationParameters = GenerationParameters(),
    val catalog: ModelCatalog = ModelCatalog(),
    val library: List<GeneratedImage> = emptyList(),
    val batch: GenerationBatch? = null,
    val isGenerating: Boolean = false,
    val notice: String = "",
    val notifyOnCompletion: Boolean = false,
    val isDownloading: Boolean = false,
    val isRefreshingModels: Boolean = false,
    val downloadMessage: String = "",
    val credentialsEncrypted: Boolean = true,
    val editDraft: EditDraft = EditDraft(),
    val isPreparingEdit: Boolean = false,
    val routerWorkers: List<RouterWorker> = emptyList()
) {
    val readyBackends: List<BackendCard>
        get() = backends.filter { it.config.enabled && it.config.isComplete && it.config.isRouter }

    val hasAnyBackend: Boolean get() = backends.isNotEmpty()

    val canAddBackend: Boolean get() = backends.none { it.config.isRouter } && backends.size < app.phonestudio.data.local.ConnectionRepository.MAX_CONNECTIONS

    /** Results of the most recent finished batch, newest backend order preserved. */
    val latestResults: List<GeneratedImage>
        get() = batch?.images.orEmpty()

    fun configFor(connectionId: String): ConnectionConfig? =
        backends.firstOrNull { it.config.id == connectionId }?.config

    /**
     * Stable per-backend colour index. Every surface that mentions a backend
     * uses it, so a colour means the same thing on the Create rail, the library
     * badge and the connection list.
     */
    fun accentIndex(connectionId: String): Int =
        routerWorkers.indexOfFirst { it.workerId == connectionId }.takeIf { it >= 0 }
            ?: backends.indexOfFirst { it.config.id == connectionId }.coerceAtLeast(0)
}

