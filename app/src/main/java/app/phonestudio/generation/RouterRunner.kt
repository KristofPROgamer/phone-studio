package app.phonestudio.generation

import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.model.*
import app.phonestudio.data.remote.ApiException
import app.phonestudio.data.remote.RouterApi
import app.phonestudio.data.remote.TransientApiException
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.WebSocket

/** One persisted parent job; the router owns fan-out, candidate storage and review. */
class RouterRunner(
    private val api: RouterApi,
    private val store: GenerationBatchStore,
    private val batchId: String,
    private val onChanged: () -> Unit
) {
    suspend fun run(config: ConnectionConfig, deadlineMillis: Long) {
        var socket: WebSocket? = null
        val wake = Channel<Unit>(Channel.CONFLATED)
        try {
            var batch = store.current()?.takeIf { it.batchId == batchId } ?: return
            val job = batch.targets.single()
            GenerationTiming.resumeIfNeeded(job.requestId)
            if (System.currentTimeMillis() >= deadlineMillis) throw ApiException("This phone's waiting period expired. Recover the saved router job before starting another render.")
            val health = api.health(config)
            if (health.service != "phone-studio-router" || health.protocolVersion != 2 || health.studioId.isBlank()) {
                throw ApiException("This connection is not a v2 Studio router. Paste the fourth notebook's connection.")
            }
            if (job.studioId.isNotBlank() && job.studioId != health.studioId) {
                throw ApiException("The router's saved session changed. Restore its original folder before recovering this request.")
            }
            report(config, true) { it.copy(state = BackendRunState.SUBMITTING, message = "Connecting to router",
                studioId = health.studioId,
                startedAtMillis = it.startedAtMillis.takeIf { start -> start > 0 } ?: System.currentTimeMillis()) }
            batch = store.current()?.takeIf { it.batchId == batchId } ?: return
            // Resolve private uploads before persisting the exact request envelope.
            if (job.promptId == null && !job.submissionAttempted && batch.edit != null) {
                var edit = requireNotNull(batch.edit)
                if (edit.sourceAssetId == null || edit.sourceConnectionId != config.id || edit.sourceStudioId != health.studioId) {
                    val asset = api.upload(config, File(edit.sourcePath), "image")
                    currentCoroutineContext().ensureActive()
                    if (asset.width != edit.width || asset.height != edit.height) throw ApiException("The source dimensions changed. Choose the source again before painting a mask.")
                    edit = edit.copy(sourceAssetId = asset.assetId, sourceConnectionId = config.id,
                        sourceStudioId = health.studioId, maskAssetId = null)
                    batch = store.updateBatch(batchId, true) { it.copy(edit = edit) } ?: return
                }
                if (edit.maskPath.isNotBlank() && edit.maskAssetId == null) {
                    val asset = api.upload(config, File(edit.maskPath), "mask")
                    currentCoroutineContext().ensureActive()
                    if (asset.width != edit.width || asset.height != edit.height) throw ApiException("The painted mask does not match the source image.")
                    edit = edit.copy(maskAssetId = asset.assetId)
                    batch = store.updateBatch(batchId, true) { it.copy(edit = edit) } ?: return
                }
            }
            var snapshot: RouterSnapshot? = null
            if (job.promptId != null) {
                snapshot = api.status(config, job.promptId)
                if (job.studioId.isNotBlank() && snapshot.studioId != job.studioId) {
                    throw ApiException("This is a different router session. Restore the original saved router folder to recover this job.")
                }
                if (batch.routerRetry) {
                    snapshot = api.retry(config, job.promptId, batch.batchId)
                    currentCoroutineContext().ensureActive()
                    batch = store.updateBatch(batchId, true) { it.copy(routerRetry = false) } ?: return
                }
            } else {
                val request = requestFor(batch)
                var maySubmit = !job.submissionAttempted
                while (snapshot == null && System.currentTimeMillis() < deadlineMillis) {
                    try {
                        if (!maySubmit) {
                            snapshot = api.recover(config, batch.clientId, job.requestId)
                            // The same key + payload is idempotent on the router. Only an authoritative
                            // missing mapping permits this replay; worker submissions are never replayed here.
                            maySubmit = snapshot == null
                        }
                        if (snapshot == null && maySubmit) {
                            report(config, true) { it.copy(submissionAttempted = true, message = "Requesting your image") }
                            currentCoroutineContext().ensureActive()
                            maySubmit = false
                            snapshot = api.submit(config, request)
                        }
                    } catch (error: TransientApiException) {
                        report(config) { it.copy(message = error.message ?: "Recovering your request") }
                        delay(2_000)
                    }
                }
            }
            val accepted = snapshot ?: throw ApiException("The router could not confirm this request. Its saved request ID remains on this phone.")
            validate(accepted, batch, config)
            apply(config, accepted)
            GenerationTiming.mark(job.requestId, "submitted", accepted.jobId)
            socket = api.watch(config, accepted.jobId) { wake.trySend(Unit) }
            var latest = accepted
            while (!latest.terminal && System.currentTimeMillis() < deadlineMillis) {
                withTimeoutOrNull(3_000) { wake.receive() }
                try {
                    val next = api.status(config, accepted.jobId)
                    validate(next, batch, config)
                    if (next.revision > latest.revision) {
                        latest = next
                        apply(config, next)
                    }
                } catch (error: TransientApiException) {
                    report(config) { it.copy(message = "Router offline; reconnecting. Your accepted job is saved.") }
                }
            }
            if (!latest.terminal) throw ApiException("The phone stopped waiting after 30 minutes. The job ID is saved; reconnect to check the router before starting another render.")
            GenerationTiming.mark(job.requestId, "outputs_ready", accepted.jobId)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            report(config, true) { it.copy(state = BackendRunState.FAILED, message = error.message ?: "Router job failed",
                failureReason = error.message ?: "Router job failed", finishedAtMillis = System.currentTimeMillis()) }
        } finally { socket?.close(1000, "Done"); wake.close() }
    }

    private fun validate(snapshot: RouterSnapshot, batch: GenerationBatch, config: ConnectionConfig) {
        if (snapshot.schemaVersion != 2 || snapshot.clientId != batch.clientId || snapshot.requestId != batch.targets.single().requestId) {
            throw ApiException("The router returned a different request. Check its session folder before retrying.")
        }
        val savedStudio = store.current()?.job(config.id)?.studioId.orEmpty()
        if (savedStudio.isNotBlank() && savedStudio != snapshot.studioId) throw ApiException("The router's saved session changed. Restore the original folder.")
    }

    private fun apply(config: ConnectionConfig, snapshot: RouterSnapshot) {
        val winner = snapshot.selection.winnerCandidateId
        val selectionStatus = if (snapshot.selection.status == "selected" && snapshot.candidates.none { it.candidateId == winner })
            "unavailable" else snapshot.selection.status
        val images = snapshot.candidates.map { candidate ->
            GeneratedImage(
                id = "${snapshot.studioId}:${candidate.candidateId}", connectionId = config.id,
                connectionName = candidate.workerName, promptId = snapshot.jobId,
                descriptor = ImageDescriptor("${candidate.assetId}.png"), prompt = candidate.originalPrompt,
                negativePrompt = candidate.negativePrompt, model = candidate.model, lora = candidate.lora,
                width = candidate.width, height = candidate.height, steps = candidate.steps, cfg = candidate.cfg,
                sampler = candidate.sampler, scheduler = candidate.scheduler, seed = candidate.seed,
                createdAtMillis = snapshot.createdAtMillis, speedExtras = candidate.speedExtras,
                negativePromptRecorded = true, loraStrength = candidate.loraStrength,
                routerAssetId = candidate.assetId, routerStudioId = snapshot.studioId, candidateId = candidate.candidateId,
                effectivePrompt = candidate.effectivePrompt, selectionStatus = selectionStatus,
                selected = candidate.candidateId == winner, selectionReason = snapshot.selection.reason,
                sourceAssetId = candidate.sourceAssetId, editInstruction = candidate.editInstruction,
                editMode = candidate.editMode, fooocusInpaint = candidate.fooocusInpaint,
                workingWidth = candidate.workingWidth, workingHeight = candidate.workingHeight,
                requestWidth = snapshot.parameters?.width ?: 0, requestHeight = snapshot.parameters?.height ?: 0,
                reviewerModel = snapshot.selection.reviewerModel, reviewerRevision = snapshot.selection.reviewerRevision,
                reviewScore = snapshot.selection.scores.firstOrNull { it.candidateId == candidate.candidateId }
            )
        }
        val saved = store.current()?.job(config.id)
        val durable = snapshot.terminal || saved?.promptId != snapshot.jobId || saved.images != images
        report(config, durable) { job -> job.copy(
            promptId = snapshot.jobId, studioId = snapshot.studioId, routerWorkers = snapshot.workers,
            routerState = snapshot.state, warnings = snapshot.warnings, images = images,
            state = if (!snapshot.terminal) BackendRunState.RUNNING else if (images.isNotEmpty()) BackendRunState.COMPLETE else BackendRunState.FAILED,
            message = snapshot.stageLabel, failureReason = if (snapshot.terminal && (images.isEmpty() || snapshot.state != "complete")) snapshot.error ?: snapshot.stageLabel else null,
            stepsDone = snapshot.workers.sumOf { it.stepsDone }, stepsTotal = snapshot.workers.sumOf { it.stepsTotal },
            finishedAtMillis = if (snapshot.terminal) System.currentTimeMillis() else 0
        ) }
    }

    private fun report(config: ConnectionConfig, durable: Boolean = false, transform: (BackendJob) -> BackendJob) {
        store.updateJob(batchId, config.id, durable, transform)
        onChanged()
    }

    companion object {
        fun requestFor(batch: GenerationBatch): RouterRequest {
            val p = batch.parameters
            val edit = batch.edit
            return RouterRequest(clientId = batch.clientId, requestId = batch.targets.single().requestId,
                operation = if (edit != null) "edit" else "generate", originalPrompt = edit?.sourcePrompt ?: p.prompt,
                negativePrompt = p.negativePrompt, parameters = RouterParameters(p.model, p.lora, p.loraStrength,
                    p.width, p.height, if (p.steps == 18) "fast" else "balanced", p.seed, p.varySeedPerBackend, p.speedExtras),
                options = RouterOptions(p.enhancePrompt, p.reviewCandidates, p.auxiliaryInpaint), sourceAssetId = edit?.sourceAssetId,
                maskAssetId = edit?.maskAssetId, editInstruction = edit?.instruction, preservation = edit?.preservation ?: 0.65f)
        }
    }
}
