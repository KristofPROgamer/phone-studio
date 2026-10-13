package app.phonestudio.ui

import android.net.Uri
import java.io.File
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.phonestudio.core.AppContainer
import app.phonestudio.data.local.AppPreferences
import app.phonestudio.data.model.ConnectionConfig
import app.phonestudio.data.model.ConnectionState
import app.phonestudio.data.model.ConnectionStatus
import app.phonestudio.data.model.ConnectionUpdates
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.ModelCatalog
import app.phonestudio.data.model.RenderPace
import app.phonestudio.data.model.EditDraft
import app.phonestudio.data.model.MaskStroke
import app.phonestudio.data.remote.ComfyApi
import app.phonestudio.data.remote.WorkflowBuilder
import app.phonestudio.generation.GenerationService
import app.phonestudio.generation.GenerationTiming
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.supervisorScope

class StudioViewModel(private val container: AppContainer) : ViewModel() {

    private val connections = container.connections
    private val preferences = container.preferences
    private val batchStore = container.batchStore
    private val api = container.api
    private val initialLibrary = preferences.loadLibrary()
    private val initialBatch = batchStore.current()
    private val initialParameters = RenderPace.normalized(
        preferences.loadParameters() ?: GenerationParameters()
    )

    private val _state = MutableStateFlow(
        StudioUiState(
            tab = if (connections.renderTargets().isEmpty()) StudioTab.CONNECT else StudioTab.CREATE,
            backends = connections.connections.value.map(::BackendCard),
            parameters = initialParameters,
            library = initialLibrary,
            batch = initialBatch,
            isGenerating = initialBatch?.isActive == true,
            notifyOnCompletion = preferences.notifyOnCompletion,
            credentialsEncrypted = connections.isEncrypted,
            editDraft = preferences.loadEditDraft()
        )
    )
    val state: StateFlow<StudioUiState> = _state.asStateFlow()

    private var mergedImageIds = initialLibrary.mapTo(mutableSetOf()) { it.id }
    // Connection checks resume on the ViewModel's main dispatcher after HTTP.
    private val warmUpsInFlight = mutableSetOf<String>()
    private val connectionChecks = mutableMapOf<String, Job>()
    private var modelRefresh: Job? = null
    private var modelDownload: Job? = null
    private var editEpoch = 0L

    init {
        // Startup normalization is part of the draft, even if the app closes
        // before the next edit or Generate tap.
        preferences.saveParameters(initialParameters)
        viewModelScope.launch {
            connections.connections.collect { saved ->
                _state.update { current ->
                    val cards = saved.map { config ->
                        current.backends.firstOrNull { it.config.id == config.id }
                            ?.takeIf { ConnectionUpdates.sameAccess(it.config, config) }
                            ?.copy(config = config) ?: BackendCard(config)
                    }
                    val union = ModelCatalog.union(cards.filter { it.config.isRouter && it.config.enabled }.map { it.catalog })
                    val parameters = normalizedParameters(current.parameters, union)
                    current.copy(backends = cards, catalog = union, parameters = parameters,
                        credentialsEncrypted = connections.isEncrypted)
                }
            }
        }
        viewModelScope.launch {
            batchStore.batch.collect { batch ->
                _state.update { current ->
                    current.copy(batch = batch, isGenerating = batch?.isActive == true)
                }
                batch?.images?.takeIf { it.isNotEmpty() }?.let(::mergeIntoLibrary)
            }
        }

        // A batch may have outlived the process. Reattach the service to it.
        if (batchStore.current()?.isActive == true) GenerationService.start(container.appContext)
        if (connections.connections.value.isNotEmpty()) checkAllBackends()
    }

    // ---- navigation and settings -----------------------------------------

    fun selectTab(tab: StudioTab) = _state.update { it.copy(tab = tab) }

    fun dismissNotice() = _state.update { it.copy(notice = "") }

    fun showNotice(message: String) = _state.update { it.copy(notice = message) }

    fun updateParameters(transform: (GenerationParameters) -> GenerationParameters) {
        _state.update { current ->
            val next = RenderPace.normalized(transform(current.parameters))
            preferences.saveParameters(next)
            current.copy(parameters = next)
        }
    }

    fun setNotifyOnCompletion(enabled: Boolean) {
        preferences.notifyOnCompletion = enabled
        _state.update { it.copy(notifyOnCompletion = enabled) }
    }

    fun chooseModel(model: String) = updateParameters { it.copy(model = model) }

    fun chooseLora(lora: String) = updateParameters { it.copy(lora = lora) }

    // ---- connections ------------------------------------------------------

    fun importConnection(config: ConnectionConfig): Boolean {
        if (!config.isRouter) {
            showNotice("Use the setup code from your router notebook.")
            return false
        }
        return saveConnection(ConnectionUpdates.importedRouter(config, connections.connections.value))
    }

    fun saveConnection(config: ConnectionConfig): Boolean {
        val existing = connections.byId(config.id)
        if (existing != null && ConnectionUpdates.activeIn(existing.id, batchStore.current()) &&
            !ConnectionUpdates.sameAccess(existing, config)) {
            showNotice("Wait for the render to finish, or stop it before changing this connection.")
            return false
        }
        val error = config.normalized().validationError()
        if (error != null) {
            _state.update { it.copy(notice = error) }
            return false
        }
        val stored = try { connections.save(config) } catch (error: IllegalArgumentException) {
            showNotice(error.message ?: "This connection could not be saved.")
            return false
        } catch (_: Exception) {
            showNotice("This connection could not be saved. Check available device storage and try again.")
            return false
        }
        connectionChecks.remove(stored.id)?.cancel()
        if (stored.isRouter && existing != null && !ConnectionUpdates.sameAccess(existing, stored)) {
            _state.update { it.copy(routerWorkers = emptyList()) }
        }
        // A saved connection is almost always a fresh Colab session, so the old
        // warm-up record no longer applies to it.
        preferences.forgetWarmUp(stored.id)
        _state.update { it.copy(notice = "Saved ${stored.displayName}.", credentialsEncrypted = connections.isEncrypted) }
        checkBackend(stored.id)
        return true
    }

    fun removeConnection(id: String) {
        if (ConnectionUpdates.activeIn(id, batchStore.current())) {
            showNotice("Wait for the render to finish, or stop it before removing this connection.")
            return
        }
        connectionChecks.remove(id)?.cancel()
        val wasRouter = connections.byId(id)?.isRouter == true
        val name = connections.byId(id)?.displayName ?: "Backend"
        connections.remove(id)
        preferences.forgetWarmUp(id)
        _state.update { current ->
            current.copy(
                backends = current.backends.filterNot { it.config.id == id },
                notice = "Removed $name.",
                routerWorkers = if (wasRouter) emptyList() else current.routerWorkers
            )
        }
        refreshCatalogUnion()
    }

    fun setConnectionEnabled(id: String, enabled: Boolean) {
        if (!enabled && ConnectionUpdates.activeIn(id, batchStore.current())) {
            showNotice("Wait for the render to finish, or stop it before disconnecting.")
            return
        }
        connectionChecks.remove(id)?.cancel()
        connections.setEnabled(id, enabled)
        if (!enabled && connections.byId(id)?.isRouter == true) {
            _state.update { it.copy(routerWorkers = emptyList()) }
        }
        if (enabled) checkBackend(id)
    }

    fun forgetEverything() {
        connectionChecks.values.forEach { it.cancel() }
        connectionChecks.clear()
        modelRefresh?.cancel()
        modelDownload?.cancel()
        editEpoch += 1
        val files = container.editFiles.savedFiles()
        GenerationService.cancel(container.appContext)
        batchStore.clear()
        connections.clearAll()
        preferences.clearAll()
        viewModelScope.launch { container.editFiles.clear(files) }
        mergedImageIds = mutableSetOf()
        _state.value = StudioUiState(
            tab = StudioTab.CONNECT,
            notice = "Removed every saved backend from this phone.",
            credentialsEncrypted = connections.isEncrypted
        )
    }

    fun checkAllBackends() {
        connections.connections.value.filter { it.enabled }.forEach { checkBackend(it.id) }
    }

    /** Health, catalog and an optional warm-up for one backend. */
    fun checkBackend(id: String) {
        val config = connections.byId(id) ?: return
        if (!config.enabled) return
        connectionChecks.remove(id)?.cancel()
        val check = viewModelScope.launch(start = CoroutineStart.LAZY) {
            setStatus(id, ConnectionStatus(ConnectionState.CHECKING, "Checking…"), expected = config)
            try {
                // Initial discovery stays bounded; explicit model refresh is uncached.
                val (health, catalogResult) = supervisorScope {
                    val healthRequest = async { api.health(config) }
                    val catalogRequest = async {
                        try { Result.success(api.listModels(config, allowCached = true)) }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (error: Exception) { Result.failure<ModelCatalog>(error) }
                    }
                    val ready = healthRequest.await()
                    if (!ready.ok) throw IllegalStateException("The bridge did not report ready.")
                    if (config.isRouter && (ready.service != "phone-studio-router" || ready.protocolVersion != 2)) {
                        throw IllegalStateException("Use the router notebook's setup code. Worker codes belong in the router notebook.")
                    }
                    ready to catalogRequest.await()
                }
                currentCoroutineContext().ensureActive()
                if (!isCurrentConnection(config)) return@launch
                val catalog = catalogResult.getOrNull()

                setStatus(
                    id,
                    ConnectionStatus(
                        state = ConnectionState.ONLINE,
                        message = if (config.isRouter) {
                            "${health.workers.count { it.online }} of ${health.workers.size} workers online · ${health.llm.statusLabel}"
                        } else if (catalog?.checkpoints?.isEmpty() == true) {
                            "Online, but no checkpoints yet"
                        } else {
                            "Online" + catalog?.let { " · ${it.checkpoints.size} checkpoints" }.orEmpty()
                        } + if (catalogResult.isFailure) " · Model list unavailable; refresh to retry" else "",
                        instanceId = health.instanceId,
                        checkpointCount = catalog?.checkpoints?.size ?: 0
                    ),
                    catalog = catalog,
                    expected = config
                )
                refreshCatalogUnion()
                if (config.isRouter) _state.update { it.copy(routerWorkers = health.workers) }
                warmUp(config, health)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (error: Exception) {
                if (config.isRouter && isCurrentConnection(config)) {
                    _state.update { it.copy(routerWorkers = emptyList()) }
                }
                setStatus(
                    id,
                    ConnectionStatus(ConnectionState.OFFLINE, error.message ?: "Could not reach this backend."),
                    expected = config
                )
            } finally {
                if (connectionChecks[id] === currentCoroutineContext()[Job]) connectionChecks.remove(id)
            }
        }
        connectionChecks[id] = check
        check.start()
    }

    fun refreshModels() {
        if (modelRefresh?.isActive == true) return
        val targets = connections.renderTargets()
        if (targets.isEmpty()) {
            selectTab(StudioTab.CONNECT)
            return
        }
        modelRefresh = viewModelScope.launch {
            _state.update { it.copy(isRefreshingModels = true) }
            try {
                val refreshed = supervisorScope {
                targets.map { config ->
                    async {
                        val catalog = try { api.listModels(config) }
                        catch (cancelled: CancellationException) { throw cancelled }
                        catch (_: Exception) { return@async false }
                        if (!isCurrentConnection(config)) return@async false
                        val existing = _state.value.backends
                            .firstOrNull { it.config.id == config.id }
                            ?.status
                            ?: ConnectionStatus()
                        setStatus(config.id, existing, catalog, expected = config)
                        true
                    }
                }.awaitAll()
                }
                refreshCatalogUnion()
                _state.update { it.copy(notice = if (refreshed.any { success -> success }) "Model list refreshed."
                    else "Could not refresh models. Check your connection and try again; saved choices are kept.") }
            } finally { _state.update { it.copy(isRefreshingModels = false) } }
        }
    }

    // ---- generation -------------------------------------------------------

    /**
     * Fans the same prompt out to every reachable backend at once.
     *
     * Reachability is decided per backend inside the runner, not here, so a
     * Colab that died since the last health check costs one short probe rather
     * than failing the press.
     */
    fun generate() {
        val tappedAt = GenerationTiming.now()
        val snapshot = _state.value
        val parameters = snapshot.parameters

        if (batchStore.current()?.isActive == true) {
            _state.update { it.copy(notice = "A render is already running.") }
            return
        }
        val targets = connections.renderTargets()
        if (targets.isEmpty()) {
            _state.update { it.copy(notice = "Connect your router first.", tab = StudioTab.CONNECT) }
            return
        }
        val edit = snapshot.editDraft.takeIf { it.enabled }
        val epoch = editEpoch
        if (snapshot.isPreparingEdit) { showNotice("Wait for the source image to finish copying."); return }
        if (edit != null && (!edit.hasSource || edit.instruction.isBlank())) {
            showNotice("Choose a source image and describe the change first."); return
        }
        if (edit?.maskMode == "manual" && edit.strokes.isEmpty()) { showNotice("Paint an area, or choose Automatic area."); return }
        if (edit == null && parameters.prompt.isBlank()) {
            _state.update { it.copy(notice = "Describe what you want to make first.") }
            return
        }
        if (parameters.model.isBlank()) {
            _state.update { it.copy(notice = "Choose a checkpoint first.", tab = StudioTab.MODELS) }
            return
        }

        viewModelScope.launch {
            _state.update { it.copy(isPreparingEdit = true) }
            try {
                val prepared = edit?.copy(maskPath = container.editFiles.mask(edit), maskAssetId = null)
                if (epoch != editEpoch) { prepared?.maskPath?.takeIf { it.isNotBlank() }?.let { File(it).delete() }; return@launch }
                val batch = container.orchestrator.createBatch(parameters, preferences.clientId(), targets, prepared)
                GenerationTiming.start(batch, tappedAt)
                batchStore.commit(batch)
                GenerationService.start(container.appContext)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { showNotice(error.message ?: "The edit could not be prepared.") }
            finally { if (epoch == editEpoch) _state.update { it.copy(isPreparingEdit = false) } }
        }
    }

    fun cancelGeneration() {
        GenerationService.cancel(container.appContext)
        _state.update { it.copy(notice = "Stopping the router job. Accepted workers may finish if cancellation is unavailable.") }
    }

    /** Re-runs only the backends that failed or were skipped, with their original seeds. */
    fun retryFailedBackends() {
        val tappedAt = GenerationTiming.now()
        val batch = batchStore.current() ?: return
        if (batch.isActive) {
            _state.update { it.copy(notice = "Wait for the other backends to finish before retrying.") }
            return
        }
        if (batch.unsuccessful.isEmpty()) return
        val retry = container.orchestrator.retryBatch(batch)
        GenerationTiming.start(retry, tappedAt)
        batchStore.commit(retry)
        GenerationService.start(container.appContext)
    }

    // ---- library ----------------------------------------------------------

    fun imageUrl(image: GeneratedImage): String? {
        val config = connections.byId(image.connectionId) ?: return null
        image.routerAssetId?.let { return container.router.assetUrl(config, it) }
        return api.viewUrl(config, image.descriptor)
    }

    fun updateEdit(transform: (EditDraft) -> EditDraft) {
        _state.update { current ->
            val next = transform(current.editDraft)
            preferences.saveEditDraft(next)
            current.copy(editDraft = next)
        }
    }

    fun addMaskStroke(stroke: MaskStroke) {
        if (_state.value.editDraft.strokes.size >= 64) { showNotice("The mask has 64 strokes. Undo a stroke or choose Automatic area to clear it."); return }
        updateEdit { it.copy(strokes = it.strokes + stroke, maskPath = "", maskAssetId = null) }
    }

    fun importSource(uri: Uri) {
        val epoch = ++editEpoch
        viewModelScope.launch {
            _state.update { it.copy(isPreparingEdit = true) }
            try {
                val imported = container.editFiles.import(uri)
                val saved = _state.value.editDraft
                val draft = imported.copy(instruction = saved.instruction, preservation = saved.preservation)
                if (epoch != editEpoch) { File(draft.sourcePath).delete(); return@launch }
                updateEdit { draft }
                _state.update { it.copy(tab = StudioTab.CREATE, notice = "Source copied. Your edit draft is saved automatically.") }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { showNotice(error.message ?: "Could not open that image.") }
            finally { if (epoch == editEpoch) _state.update { it.copy(isPreparingEdit = false) } }
        }
    }

    fun editImage(image: GeneratedImage) {
        val url = imageUrl(image) ?: run { showNotice("Reconnect this image's saved connection to load the source."); return }
        val epoch = ++editEpoch
        viewModelScope.launch {
            _state.update { it.copy(isPreparingEdit = true, tab = StudioTab.CREATE) }
            val raw = container.editFiles.newFile(".source")
            try {
                container.router.copyImage(url, raw)
                val saved = _state.value.editDraft
                var draft = container.editFiles.normalize(raw).copy(sourcePrompt = image.prompt,
                    instruction = saved.instruction, preservation = saved.preservation)
                if (epoch != editEpoch) { File(draft.sourcePath).delete(); return@launch }
                if (image.routerAssetId != null) draft = draft.copy(sourceAssetId = image.routerAssetId,
                    sourceConnectionId = image.connectionId, sourceStudioId = image.routerStudioId)
                updateParameters { image.toParameters(it).copy(prompt = it.prompt, negativePrompt = it.negativePrompt,
                    seed = app.phonestudio.data.model.Seeds.AUTO) }
                updateEdit { draft }
                showNotice("Source saved. Describe what you want to change.")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { showNotice(error.message ?: "Could not copy the source image.") }
            finally { raw.delete(); if (epoch == editEpoch) _state.update { it.copy(isPreparingEdit = false) } }
        }
    }

    /** Coil has decoded the visible result; this precedes frame presentation. */
    fun imageReady(image: GeneratedImage) {
        val job = batchStore.current()?.job(image.connectionId) ?: return
        if (job.promptId == image.promptId) {
            GenerationTiming.mark(job.requestId, "image_ready", image.promptId)
        }
    }

    fun useSettingsFrom(image: GeneratedImage) {
        updateParameters { image.toParameters(it) }
        _state.update {
            val pace = RenderPace.forSteps(it.parameters.steps) ?: RenderPace.BALANCED
            it.copy(tab = StudioTab.CREATE, notice = "Loaded image settings with the ${pace.label} preset.")
        }
    }

    fun reuseSeed(image: GeneratedImage) {
        updateParameters { it.copy(seed = image.seed) }
        _state.update { it.copy(notice = "Seed ${image.seed} pinned for the next render.") }
    }

    fun saveToGallery(image: GeneratedImage) {
        val url = imageUrl(image)
        if (url == null) {
            _state.update { it.copy(notice = "That backend is no longer saved, so the file cannot be fetched.") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(notice = "Saving…") }
            val result = container.imageExporter.saveToGallery(url, image.descriptor.filename)
            _state.update { current ->
                current.copy(
                    notice = result.fold(
                        onSuccess = { "Saved to $it." },
                        onFailure = { error -> error.message ?: "Could not save that image." }
                    )
                )
            }
        }
    }

    fun clearLibrary() {
        mergedImageIds = mutableSetOf()
        preferences.saveLibrary(emptyList())
        _state.update { it.copy(library = emptyList(), notice = "Library cleared.") }
    }

    // ---- model downloads --------------------------------------------------

    /**
     * Civitai downloads run on one backend at a time, because each backend has
     * its own Drive folder and its own API key.
     */
    fun downloadCivitaiModel(input: String, kind: String, connectionId: String?) {
        if (_state.value.isDownloading) {
            showNotice("A model download is already running.")
            return
        }
        val versionId = extractVersionId(input)
        if (versionId == null) {
            _state.update {
                it.copy(downloadMessage = "Paste a model-version ID, or a URL containing modelVersionId=12345.")
            }
            return
        }
        val config = connectionId?.let { connections.byId(it) } ?: connections.renderTargets().firstOrNull()
        if (config == null) {
            _state.update { it.copy(downloadMessage = "Connect a backend first.") }
            return
        }

        modelDownload = viewModelScope.launch {
            _state.update { it.copy(isDownloading = true, downloadMessage = "Starting download on ${config.displayName}…") }
            try {
                val jobId = api.beginModelDownload(config, versionId, kind)
                var waited = 0L
                while (waited < DOWNLOAD_TIMEOUT_MS) {
                    // Multi-gigabyte downloads do not need second-by-second
                    // polling; the interval widens once the transfer is under way.
                    val interval = if (waited < 20_000L) 1_500L else 5_000L
                    delay(interval)
                    waited += interval

                    val status = api.downloadStatus(config, jobId)
                    val percent = status.progress?.let { " ${it.toInt()}%" }.orEmpty()
                    _state.update {
                        it.copy(downloadMessage = status.status.replaceFirstChar(Char::uppercase) + percent)
                    }
                    when (status.status.lowercase()) {
                        "complete" -> {
                            _state.update {
                                it.copy(isDownloading = false, downloadMessage = "${status.filename ?: "Model"} is ready.")
                            }
                            refreshModels()
                            return@launch
                        }
                        "partial" -> {
                            val failed = status.workers.filter { it.status in setOf("failed", "error") }.joinToString { it.name }
                            _state.update { it.copy(isDownloading = false,
                                downloadMessage = "Downloaded on some workers. ${failed.ifBlank { "Some workers" }} could not finish; check their connection and refresh availability.") }
                            refreshModels()
                            return@launch
                        }
                        "failed" -> throw IllegalStateException(status.error ?: "The download failed.")
                    }
                }
                throw IllegalStateException("The download timed out. Check the Colab notebook.")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) {
                _state.update {
                    it.copy(isDownloading = false, downloadMessage = error.message ?: "Could not download that model.")
                }
            } finally { _state.update { it.copy(isDownloading = false) } }
        }
    }

    // ---- internals --------------------------------------------------------

    private fun isCurrentConnection(config: ConnectionConfig): Boolean =
        connections.byId(config.id)?.let { ConnectionUpdates.sameAccess(it, config) } == true

    private fun setStatus(id: String, status: ConnectionStatus, catalog: ModelCatalog? = null,
                          expected: ConnectionConfig? = null) {
        if (expected != null && !isCurrentConnection(expected)) return
        _state.update { current ->
            current.copy(
                backends = current.backends.map { card ->
                    if (card.config.id == id && (expected == null || ConnectionUpdates.sameAccess(card.config, expected))) {
                        card.copy(status = status, catalog = catalog ?: card.catalog)
                    } else {
                        card
                    }
                }
            )
        }
    }

    private fun refreshCatalogUnion() {
        _state.update { current ->
            val union = ModelCatalog.union(current.backends.filter { it.config.isRouter && it.config.enabled }.map { it.catalog })
            current.copy(
                catalog = union,
                parameters = normalizedParameters(current.parameters, union)
            )
        }
    }

    private fun normalizedParameters(
        parameters: GenerationParameters,
        catalog: ModelCatalog
    ): GenerationParameters {
        // Keep an explicit saved choice even while backends are still being
        // checked (or temporarily offline). Clearing it on the first partial
        // catalog response made model selection jump unpredictably at startup.
        val model = parameters.model.ifBlank { catalog.checkpoints.firstOrNull().orEmpty() }
        return RenderPace.normalized(parameters.copy(model = model)).also { normalized ->
            if (normalized != parameters) preferences.saveParameters(normalized)
        }
    }

    /**
     * Sends a one-step preview at the resolution the user is about to render.
     *
     * cuDNN autotuning caches kernels per tensor shape, so the previous fixed
     * 128×128 warm-up tuned shapes that no real render ever used and left the
     * first visible image paying the full autotune cost.
     */
    private suspend fun warmUp(config: ConnectionConfig, health: ComfyApi.ServerHealth) {
        if (config.isRouter) return // Worker notebook startup owns its model warm-up.
        val parameters = _state.value.parameters
        if (parameters.model.isBlank()) return
        if (batchStore.current()?.isActive == true) return
        if (!warmUpsInFlight.add(config.id)) return
        try {
            val completed = health.completedWarmup
            if (completed != null && completed.promptId.isNotBlank() &&
                completed.guidanceMode == "cfg" && parameters.cfg > 1f && parameters.lora.isBlank() &&
                completed.model == parameters.model && completed.width == parameters.width &&
                completed.height == parameters.height && completed.sampler == parameters.sampler &&
                completed.scheduler == parameters.scheduler) {
                // Reuse only this confirmed startup preview. Do not persist it as
                // a CFG-1 app preview; a later guidance/LoRA choice may need one.
                return
            }

            val signature = listOf(
                config.serverUrl,
                health.instanceId.ifBlank { "unknown" },
                parameters.model,
                "${parameters.width}x${parameters.height}",
                parameters.sampler,
                parameters.scheduler
            ).joinToString("|")
            if (preferences.hasWarmedUp(config.id, signature)) return

            try {
                api.warmUp(
                    config = config,
                    workflow = WorkflowBuilder.warmUp(
                        model = parameters.model,
                        width = parameters.width,
                        height = parameters.height,
                        sampler = parameters.sampler,
                        scheduler = parameters.scheduler
                    ),
                    clientId = preferences.clientId()
                )
                preferences.markWarmedUp(config.id, signature)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { /* An optional legacy preview cannot prevent connecting. */ }
            // Warm-up is optional; accepted app previews keep the existing record behavior.
        } finally {
            warmUpsInFlight.remove(config.id)
        }
    }

    private fun mergeIntoLibrary(images: List<GeneratedImage>) {
        _state.update { current ->
            val updates = images.associateBy { it.id }
            val fresh = images.filterNot { image -> current.library.any { it.id == image.id } }
            val merged = (fresh + current.library.map { updates[it.id] ?: it })
                .distinctBy { it.id }
                .take(AppPreferences.LIBRARY_LIMIT)
            if (merged != current.library) preferences.saveLibrary(merged)
            mergedImageIds = merged.mapTo(mutableSetOf()) { it.id }
            current.copy(library = merged)
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

    companion object {
        private const val DOWNLOAD_TIMEOUT_MS = 20 * 60 * 1_000L

        fun factory(container: AppContainer): ViewModelProvider.Factory = viewModelFactory {
            initializer { StudioViewModel(container) }
        }
    }
}
