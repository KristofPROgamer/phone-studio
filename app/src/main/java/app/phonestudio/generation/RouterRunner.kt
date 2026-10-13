package app.phonestudio.generation

import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.local.BatchStorageException
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
    private val onChanged: () -> Unit,
    private val timing: (String, String, String?) -> Unit = { requestId, stage, promptId ->
        if (stage == "resumed") GenerationTiming.resumeIfNeeded(requestId)
        else GenerationTiming.mark(requestId, stage, promptId)
    }
) {
    suspend fun run(config: ConnectionConfig, deadlineMillis: Long) {
        var socket: WebSocket? = null
        val wake = Channel<Unit>(Channel.CONFLATED)
        try {
            var batch = store.current()?.takeIf { it.batchId == batchId } ?: return
            val job = batch.targets.single()
            timing(job.requestId, "resumed", null)
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
                validate(snapshot, batch, config)
                val retryEligible = batch.routerRetry && snapshot.terminal && snapshot.workers.any {
                        it.state in setOf("failed", "skipped", "cancelled")
                    } && snapshot.workers.none { it.state == "submission_uncertain" }
                applySnapshot(config, snapshot, keepActive = retryEligible)
                if (retryEligible) {
                    val retryId = batch.routerRetryRequestId ?: batch.batchId
                    // Reserve the action key before POST; an ambiguous reply reuses it.
                    batch = store.updateBatch(batchId, true) { it.copy(routerRetryRequestId = retryId) } ?: return
                    snapshot = api.retry(config, job.promptId, retryId)
                    currentCoroutineContext().ensureActive()
                    validate(snapshot, batch, config)
                }
                batch = store.updateBatch(batchId, true) { it.copy(routerRetry = false, routerRetryRequestId = null) } ?: return
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
            applySnapshot(config, accepted)
            timing(job.requestId, "submitted", accepted.jobId)
            socket = api.watch(config, accepted.jobId) { wake.trySend(Unit) }
            var latest = accepted
            while (!latest.terminal && System.currentTimeMillis() < deadlineMillis) {
                withTimeoutOrNull(3_000) { wake.receive() }
                try {
                    val next = api.status(config, accepted.jobId)
                    validate(next, batch, config)
                    if (next.revision > latest.revision) {
                        latest = next
                        applySnapshot(config, next)
                    }
                } catch (error: TransientApiException) {
                    report(config) { it.copy(message = "Router offline; reconnecting. Your accepted job is saved.") }
                }
            }
            if (!latest.terminal) throw ApiException("The phone stopped waiting after 30 minutes. The job ID is saved; reconnect to check the router before starting another render.")
            timing(job.requestId, "outputs_ready", accepted.jobId)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: BatchStorageException) {
            store.failInMemory(batchId, config.id)
            onChanged()
        } catch (error: Exception) {
            try {
                report(config, true) { it.copy(state = BackendRunState.FAILED, message = error.message ?: "Router job failed",
                    failureReason = error.message ?: "Router job failed", finishedAtMillis = System.currentTimeMillis(),
                    recoveryRequired = it.recoveryRequired || it.submissionAttempted || it.promptId != null) }
            } catch (_: BatchStorageException) { store.failInMemory(batchId, config.id); onChanged() }
        } finally { socket?.close(1000, "Done"); wake.close() }
    }

    internal suspend fun cancel(config: ConnectionConfig, batch: GenerationBatch) {
        val job = batch.targets.single()
        val submitted = job.submissionAttempted || job.promptId != null
        val snapshot = if (submitted) {
            val health = api.health(config)
            if (health.service != "phone-studio-router" || health.protocolVersion != 2 ||
                health.studioId.isBlank() || (job.studioId.isNotBlank() && job.studioId != health.studioId)) {
                throw ApiException("Cancellation could not be confirmed in the saved router session.")
            }
            fun validate(saved: app.phonestudio.data.model.RouterSnapshot) {
                if (saved.schemaVersion != 2 || saved.clientId != batch.clientId || saved.requestId != job.requestId ||
                    saved.studioId != health.studioId || (job.promptId != null && saved.jobId != job.promptId)) {
                    throw ApiException("Cancellation returned a different saved request. Restore the original router session.")
                }
            }
            val accepted = job.promptId?.let { api.status(config, it) }
                ?: api.recover(config, batch.clientId, job.requestId)
                ?: throw ApiException("Cancellation could not be confirmed. Recover the saved request before submitting again.")
            validate(accepted)
            api.cancel(config, accepted.jobId).also { cancelled ->
                validate(cancelled)
                val unconfirmed = cancelled.workers.any { it.state == "submission_uncertain" } || !cancelled.terminal
                applySnapshot(config, cancelled, cancellationUnconfirmed = unconfirmed)
                if (unconfirmed) {
                    throw ApiException("Remote cancellation was not confirmed. The accepted request remains saved for recovery.")
                }
            }
        } else null
        if (snapshot != null && snapshot.state != "cancelled") return // Work already finished; keep its stored candidates.
        store.updateJob(batch.batchId, config.id, true) {
            it.copy(state = if (it.images.isEmpty()) BackendRunState.SKIPPED else BackendRunState.COMPLETE,
                message = "Stopped", routerState = "cancelled", promptId = snapshot?.jobId ?: it.promptId,
                failureReason = "Stopped by you", finishedAtMillis = System.currentTimeMillis())
        }
    }

    private fun validate(snapshot: RouterSnapshot, batch: GenerationBatch, config: ConnectionConfig) {
        if (snapshot.schemaVersion != 2 || snapshot.clientId != batch.clientId || snapshot.requestId != batch.targets.single().requestId) {
            throw ApiException("The router returned a different request. Check its session folder before retrying.")
        }
        val knownJob = batch.targets.single().promptId
        if (knownJob != null && snapshot.jobId != knownJob) throw ApiException("The router returned a different saved job. Restore the original session before retrying.")
        val savedStudio = store.current()?.job(config.id)?.studioId.orEmpty()
        if (savedStudio.isNotBlank() && savedStudio != snapshot.studioId) throw ApiException("The router's saved session changed. Restore the original folder.")
    }

    internal fun applySnapshot(config: ConnectionConfig, snapshot: RouterSnapshot, keepActive: Boolean = false,
        cancellationUnconfirmed: Boolean = false) {
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
        val durable = cancellationUnconfirmed || snapshot.terminal || saved?.promptId != snapshot.jobId || saved.images != images
        report(config, durable) { job -> job.copy(
            promptId = snapshot.jobId, studioId = snapshot.studioId, routerWorkers = snapshot.workers,
            routerState = if (cancellationUnconfirmed) "cancellation_unconfirmed" else snapshot.state, warnings = snapshot.warnings, images = images,
            recoveryRequired = cancellationUnconfirmed || !snapshot.terminal || snapshot.state == "submission_uncertain" || snapshot.workers.any { it.state == "submission_uncertain" },
            state = if (cancellationUnconfirmed) BackendRunState.FAILED else if (keepActive) BackendRunState.SUBMITTING else if (!snapshot.terminal) BackendRunState.RUNNING else if (images.isNotEmpty()) BackendRunState.COMPLETE else BackendRunState.FAILED,
            message = if (cancellationUnconfirmed) "Remote cancellation was not confirmed" else snapshot.stageLabel,
            failureReason = if (cancellationUnconfirmed) "Recover the saved request before submitting again."
                else if (snapshot.terminal && (images.isEmpty() || snapshot.state != "complete")) snapshot.error ?: snapshot.stageLabel else null,
            stepsDone = snapshot.workers.sumOf { it.stepsDone }, stepsTotal = snapshot.workers.sumOf { it.stepsTotal },
            finishedAtMillis = if (cancellationUnconfirmed || snapshot.terminal) System.currentTimeMillis() else 0
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
