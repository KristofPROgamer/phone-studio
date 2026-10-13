package app.phonestudio

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import app.phonestudio.data.ApiException
import app.phonestudio.data.ComfyApi
import app.phonestudio.data.ConnectionConfig
import app.phonestudio.data.ConnectionStatus
import app.phonestudio.data.GenerationTracker
import app.phonestudio.data.GenerationParameters
import app.phonestudio.data.ModelCatalog
import app.phonestudio.data.StudioPreferences
import app.phonestudio.data.StudioTab
import app.phonestudio.data.StudioUiState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

class StudioViewModel(context: Context) : ViewModel() {
    private val appContext = context.applicationContext
    private val preferences = StudioPreferences(appContext)
    private val api = ComfyApi()
    private val _state = MutableStateFlow(
        StudioUiState(
            config = preferences.load(),
            notifyOnCompletion = preferences.notifyOnCompletion()
        )
    )
    val state: StateFlow<StudioUiState> = _state.asStateFlow()

    init {
        GenerationTracker.initialize(appContext)
        viewModelScope.launch {
            GenerationTracker.progress.collect { progress ->
                _state.update { current ->
                    val mergedImages = (progress.images + current.images)
                        .distinctBy { image -> image.id }
                        .take(40)
                    current.copy(
                        isGenerating = progress.isActive,
                        generationMessage = progress.message,
                        images = mergedImages
                    )
                }
            }
        }
        if (GenerationTracker.current(appContext).isActive) {
            GenerationService.start(appContext)
        }
        if (_state.value.config.serverUrl.isNotBlank()) connect()
    }

    fun selectTab(tab: StudioTab) {
        _state.update { it.copy(tab = tab) }
    }

    fun updateParameters(transform: (GenerationParameters) -> GenerationParameters) {
        _state.update { it.copy(parameters = transform(it.parameters)) }
    }

    fun setNotifyOnCompletion(enabled: Boolean) {
        preferences.setNotifyOnCompletion(enabled)
        _state.update { it.copy(notifyOnCompletion = enabled) }
    }

    fun saveConnection(config: ConnectionConfig) {
        val clean = config.copy(serverUrl = config.serverUrl.trim().trimEnd('/'))
        preferences.save(clean)
        _state.update {
            it.copy(
                config = clean,
                connectionStatus = ConnectionStatus.IDLE,
                connectionMessage = "Connection saved. Test it when Colab is running."
            )
        }
    }

    fun forgetConnection() {
        GenerationService.cancel(appContext)
        preferences.clear()
        _state.update {
            StudioUiState(
                tab = StudioTab.CONNECT,
                connectionMessage = "Connection details removed from this device."
            )
        }
    }

    fun connect() {
        val config = _state.value.config
        if (config.serverUrl.isBlank() || config.studioToken.isBlank()) {
            _state.update {
                it.copy(
                    connectionStatus = ConnectionStatus.ERROR,
                    connectionMessage = "Add the server URL and Studio token from the Colab cell."
                )
            }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(connectionStatus = ConnectionStatus.CONNECTING, connectionMessage = "Checking the Colab studio…") }
            try {
                val health = api.checkHealth(config)
                if (!health.ok) throw ApiException("The Phone Studio bridge did not report ready.")
                val catalog = api.listModels(config)
                applyCatalog(catalog)
                warmUpIfNeeded(config, health.instanceId, _state.value.parameters.model)
                _state.update {
                    it.copy(
                        connectionStatus = ConnectionStatus.CONNECTED,
                        connectionMessage = if (catalog.checkpoints.isEmpty()) "Connected. Add a checkpoint in Models to create images." else "Connected to your Colab studio."
                    )
                }
            } catch (error: Exception) {
                _state.update {
                    it.copy(
                        connectionStatus = ConnectionStatus.ERROR,
                        connectionMessage = error.message ?: "Could not connect to Colab."
                    )
                }
            }
        }
    }

    fun refreshModels() {
        val config = _state.value.config
        if (config.serverUrl.isBlank()) {
            selectTab(StudioTab.CONNECT)
            return
        }
        viewModelScope.launch {
            try {
                applyCatalog(api.listModels(config))
                _state.update { it.copy(connectionMessage = "Model list refreshed.") }
            } catch (error: Exception) {
                _state.update { it.copy(connectionMessage = error.message ?: "Could not refresh models.") }
            }
        }
    }

    fun chooseModel(model: String) {
        updateParameters { it.copy(model = model) }
    }

    fun generate() {
        val snapshot = _state.value
        val params = snapshot.parameters
        if (GenerationTracker.current(appContext).isActive) {
            _state.update { it.copy(generationMessage = "A render is already running in the background.") }
            return
        }
        if (params.prompt.isBlank()) {
            _state.update { it.copy(generationMessage = "Describe what you want to make first.") }
            return
        }
        if (params.model.isBlank()) {
            _state.update { it.copy(generationMessage = "Choose a checkpoint model first.", tab = StudioTab.MODELS) }
            return
        }
        GenerationTracker.queue(
            context = appContext,
            config = snapshot.config,
            parameters = params,
            clientId = preferences.clientId()
        )
        GenerationService.start(appContext)
    }

    fun downloadCivitaiModel(input: String, kind: String) {
        val versionId = extractVersionId(input)
        if (versionId == null) {
            _state.update {
                it.copy(downloadMessage = "Paste a Civitai model-version ID, or a URL containing modelVersionId=12345.")
            }
            return
        }
        val config = _state.value.config
        viewModelScope.launch {
            _state.update { it.copy(isDownloading = true, downloadMessage = "Starting Civitai download…") }
            try {
                val jobId = api.beginModelDownload(config, versionId, kind)
                repeat(900) {
                    delay(1_000)
                    val status = api.downloadStatus(config, jobId)
                    val progress = status.progress?.let { " ${it.toInt()}%" }.orEmpty()
                    _state.update { current -> current.copy(downloadMessage = "${status.status.replaceFirstChar { char -> char.uppercase() }}$progress") }
                    when (status.status.lowercase()) {
                        "complete" -> {
                            _state.update { it.copy(isDownloading = false, downloadMessage = "${status.filename ?: "Model"} is ready.") }
                            refreshModels()
                            return@launch
                        }
                        "failed" -> throw ApiException(status.error ?: "Civitai download failed.")
                    }
                }
                throw ApiException("The model download timed out. Check the Colab notebook.")
            } catch (error: Exception) {
                _state.update { it.copy(isDownloading = false, downloadMessage = error.message ?: "Could not download model.") }
            }
        }
    }

    private fun applyCatalog(catalog: ModelCatalog) {
        _state.update { current ->
            val selected = current.parameters.model
            val model = if (selected in catalog.checkpoints) selected else catalog.checkpoints.firstOrNull().orEmpty()
            current.copy(catalog = catalog, parameters = current.parameters.copy(model = model))
        }
    }

    private suspend fun warmUpIfNeeded(config: ConnectionConfig, instanceId: String, model: String) {
        if (model.isBlank() || GenerationTracker.current(appContext).isActive) return
        val warmupKey = "${config.serverUrl}|${instanceId.ifBlank { "unknown" }}|$model"
        if (preferences.hasCompletedWarmup(warmupKey)) return

        try {
            _state.update { it.copy(connectionMessage = "Connected. Warming the GPU for your first image…") }
            api.warmUp(config, model, preferences.clientId())
            preferences.markWarmupCompleted(warmupKey)
            _state.update { it.copy(connectionMessage = "Connected. GPU warm-up started in the background.") }
        } catch (_: Exception) {
            // Warm-up is an optional optimization. A successful health check is
            // still a usable connection, so it must not block the studio.
        }
    }

    private fun extractVersionId(input: String): String? {
        val value = input.trim()
        if (value.matches(Regex("\\d+"))) return value
        return Regex("(?:modelVersionId=|model-versions/)(\\d+)", RegexOption.IGNORE_CASE)
            .find(value)
            ?.groupValues
            ?.getOrNull(1)
    }
}

class StudioViewModelFactory(private val context: Context) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        if (modelClass.isAssignableFrom(StudioViewModel::class.java)) return StudioViewModel(context) as T
        throw IllegalArgumentException("Unknown ViewModel class")
    }
}
