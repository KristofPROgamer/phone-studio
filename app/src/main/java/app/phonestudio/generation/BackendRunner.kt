package app.phonestudio.generation

import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.local.BatchStorageException
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.BackendRunState
import app.phonestudio.data.model.ConnectionConfig
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.ImageDescriptor
import app.phonestudio.data.remote.ApiException
import app.phonestudio.data.remote.BackendUnreachableException
import app.phonestudio.data.remote.ComfyApi
import app.phonestudio.data.remote.ComfyEvent
import app.phonestudio.data.remote.ComfyEventStream
import app.phonestudio.data.remote.TransientApiException
import app.phonestudio.data.remote.WorkflowBuilder
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.min
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.WebSocket

private class ConfirmedBackendFailure(message: String) : ApiException(message)

/**
 * Runs one backend's share of a batch: probe, submit (or recover), follow, collect.
 *
 * One instance per backend per batch. Everything it learns is written straight
 * into the shared [GenerationBatchStore], so the notification and the UI see
 * per-backend state without the runner knowing either exists.
 */
class BackendRunner(
    private val api: ComfyApi,
    private val events: ComfyEventStream,
    private val store: GenerationBatchStore,
    private val batchId: String,
    private val onChanged: () -> Unit = {}
) {

    suspend fun run(
        config: ConnectionConfig,
        connectionId: String,
        parameters: GenerationParameters,
        clientId: String,
        deadlineMillis: Long
    ) {
        var socket: WebSocket? = null
        try {
            val existing = job(connectionId) ?: return
            GenerationTiming.resumeIfNeeded(existing.requestId)
            if (System.currentTimeMillis() >= deadlineMillis) {
                fail(connectionId, TIMEOUT_MESSAGE)
                return
            }
            report(connectionId, durable = false) {
                it.copy(
                    state = BackendRunState.PROBING,
                    message = "Checking backend",
                    startedAtMillis = if (it.startedAtMillis == 0L) System.currentTimeMillis() else it.startedAtMillis
                )
            }

            // A resumed job already has a prompt ID, so it skips straight to
            // following the render rather than re-probing a backend it is
            // demonstrably already talking to.
            if (existing.promptId == null) {
                val remaining = (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L)
                val ready = withTimeoutOrNull(remaining) {
                    probe(config, connectionId, parameters) != null
                } ?: throw ApiException(TIMEOUT_MESSAGE)
                if (!ready) return
                GenerationTiming.mark(existing.requestId, "probe_complete")
            }

            val promptId = job(connectionId)?.promptId ?: submitOrRecover(
                config = config,
                connectionId = connectionId,
                parameters = parameters,
                clientId = clientId,
                deadlineMillis = deadlineMillis
            )
            GenerationTiming.mark(existing.requestId, "submitted", promptId)
            val wake = Channel<Unit>(Channel.CONFLATED)
            val terminalWake = Channel<Unit>(Channel.CONFLATED)
            val terminalSeen = AtomicBoolean(false)
            val socketAlive = AtomicBoolean(false)
            val backendFailure = AtomicReference<String?>(null)

            socket = events.open(config, clientId, promptId) { event ->
                when (event) {
                    ComfyEvent.Connected -> socketAlive.set(true)
                    ComfyEvent.Disconnected -> {
                        socketAlive.set(false)
                        wake.trySend(Unit)
                    }
                    is ComfyEvent.Progress -> {
                        socketAlive.set(true)
                        report(connectionId) {
                            it.copy(
                                state = BackendRunState.RUNNING,
                                stepsDone = event.step,
                                stepsTotal = event.totalSteps,
                                message = if (event.step >= event.totalSteps) "Finalizing image"
                                    else "Sampling ${event.step}/${event.totalSteps}"
                            )
                        }
                    }
                    ComfyEvent.Finished -> {
                        socketAlive.set(true)
                        if (terminalSeen.compareAndSet(false, true)) {
                            terminalWake.trySend(Unit)
                        }
                        // A later end marker may follow the first success frame
                        // after ComfyUI has written history. It can wake an idle
                        // poll, but must not repeatedly cancel active GETs.
                        wake.trySend(Unit)
                    }
                    is ComfyEvent.Failed -> {
                        socketAlive.set(true)
                        backendFailure.set(event.message)
                        if (terminalSeen.compareAndSet(false, true)) {
                            terminalWake.trySend(Unit)
                        }
                        wake.trySend(Unit)
                    }
                }
            }

            report(connectionId) {
                it.copy(state = BackendRunState.RUNNING, message = "Rendering")
            }

            val images = follow(
                config = config,
                connectionId = connectionId,
                promptId = promptId,
                parameters = parameters,
                deadlineMillis = deadlineMillis,
                wake = wake,
                terminalWake = terminalWake,
                socketAlive = socketAlive::get,
                backendFailure = backendFailure::get
            )
            GenerationTiming.mark(existing.requestId, "history_ready", promptId)

            report(connectionId, durable = true) {
                it.copy(
                    state = BackendRunState.COMPLETE,
                    message = "Done",
                    images = images,
                    recoveryRequired = false,
                    stepsDone = it.stepsTotal,
                    finishedAtMillis = System.currentTimeMillis()
                )
            }
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: BatchStorageException) {
            store.failInMemory(batchId, connectionId)
            onChanged()
        } catch (confirmed: ConfirmedBackendFailure) {
            try { fail(connectionId, confirmed.message ?: "The earlier render failed", confirmed = true) }
            catch (_: BatchStorageException) { store.failInMemory(batchId, connectionId); onChanged() }
        } catch (unreachable: BackendUnreachableException) {
            try { skip(connectionId, unreachable.message ?: "Did not respond") }
            catch (_: BatchStorageException) { store.failInMemory(batchId, connectionId); onChanged() }
        } catch (error: Exception) {
            try { fail(connectionId, error.message ?: "Render did not finish") }
            catch (_: BatchStorageException) { store.failInMemory(batchId, connectionId); onChanged() }
        } finally {
            socket?.cancel()
        }
    }

    /**
     * Health plus catalog. A backend that cannot answer in a few seconds is
     * skipped rather than allowed to hold the batch open, and a backend that
     * simply lacks the chosen checkpoint is skipped with a reason the user can
     * act on instead of silently rendering with a different model.
     */
    private suspend fun probe(
        config: ConnectionConfig,
        connectionId: String,
        parameters: GenerationParameters
    ): Unit? = coroutineScope {
        // These reads are independent. Only this preflight permits a short-lived
        // server catalog cache; explicit Refresh/connection checks stay fresh.
        val healthRequest = async { api.health(config) }
        val catalogRequest = async {
            try {
                api.listModels(config, allowCached = true)
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null // Let ComfyUI validate the graph if this optional check fails.
            }
        }
        val health = healthRequest.await()
        if (!health.ok) {
            catalogRequest.cancel()
            skip(connectionId, "Bridge is not ready")
            return@coroutineScope null
        }

        val catalog = catalogRequest.await() ?: return@coroutineScope Unit
        if (parameters.model.isNotBlank() && parameters.model !in catalog.checkpoints) {
            skip(connectionId, "Does not have ${parameters.model.substringAfterLast('/')}")
            return@coroutineScope null
        }
        if (parameters.lora.isNotBlank() && parameters.lora !in catalog.loras) {
            skip(connectionId, "Does not have ${parameters.lora.substringAfterLast('/')}")
            return@coroutineScope null
        }
        Unit
    }

    private suspend fun submitOrRecover(
        config: ConnectionConfig,
        connectionId: String,
        parameters: GenerationParameters,
        clientId: String,
        deadlineMillis: Long
    ): String {
        val current = job(connectionId) ?: throw ApiException("This backend is no longer part of the batch.")

        // Only look for an earlier submission when one was actually attempted:
        // a fresh target must never attach itself to a previous prompt.
        if (current.submissionAttempted) {
            recoverBeforeResubmitting(config, current, clientId, deadlineMillis)
                ?.let { return storePromptId(connectionId, it) }
        }

        // Probing and recovery both involve network calls. They may have begun
        // inside the batch window but finished after it; never create a fresh
        // remote render that the now-expired foreground job will not follow.
        if (System.currentTimeMillis() >= deadlineMillis) {
            throw ApiException(TIMEOUT_MESSAGE)
        }

        report(connectionId, durable = true) {
            it.copy(state = BackendRunState.SUBMITTING, submissionAttempted = true, message = "Submitting")
        }

        val workflow = WorkflowBuilder.textToImage(parameters, current.seed)
        return try {
            val promptId = api.submit(
                config, workflow, clientId, current.requestId,
                speedExtras = parameters.speedExtras
            )
            storePromptId(connectionId, promptId)
        } catch (error: TransientApiException) {
            // A lost HTTP response is ambiguous: the prompt may already be
            // queued. Ask the bridge before risking a duplicate render.
            report(connectionId) { it.copy(message = "Checking whether it arrived") }
            repeat(RECOVERY_ATTEMPTS) {
                delay(min(RECOVERY_INTERVAL_MS,
                    (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L)))
                try {
                    recover(config, current, clientId, deadlineMillis)?.let { promptId ->
                        return storePromptId(connectionId, promptId)
                    }
                } catch (_: TransientApiException) {
                    // Keep the original ambiguous-submit error as the cause.
                }
            }
            throw ApiException("Could not confirm the render was received", error)
        }
    }

    /**
     * A persisted `submissionAttempted` flag means the previous process may
     * have died after ComfyUI accepted the prompt but before its prompt ID was
     * stored. Never resubmit merely because the recovery request itself lost
     * the network: only an authoritative `none` response makes a new submit
     * safe.
     */
    private suspend fun recoverBeforeResubmitting(
        config: ConnectionConfig,
        job: BackendJob,
        clientId: String,
        deadlineMillis: Long
    ): String? {
        var receivedAuthoritativeReply = false
        var lastTransient: TransientApiException? = null

        repeat(RECOVERY_ATTEMPTS) { attempt ->
            try {
                val promptId = recover(config, job, clientId, deadlineMillis)
                receivedAuthoritativeReply = true
                if (promptId != null) return promptId
            } catch (error: TransientApiException) {
                lastTransient = error
            }
            if (attempt < RECOVERY_ATTEMPTS - 1) delay(min(RECOVERY_INTERVAL_MS,
                (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L)))
        }

        if (!receivedAuthoritativeReply) {
            throw ApiException("Could not verify the earlier render submission", lastTransient)
        }
        return null
    }

    private suspend fun recover(
        config: ConnectionConfig,
        job: BackendJob,
        clientId: String,
        deadlineMillis: Long
    ): String? {
        if (job.requestId.isBlank()) {
            throw ApiException("The earlier render has no request ID. Check Colab before retrying.")
        }
        val remaining = (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L)
        val latest = withTimeoutOrNull(remaining) {
            api.latestJob(config, clientId, job.requestId)
        } ?: throw ApiException(TIMEOUT_MESSAGE)
        if (latest.requestId == job.requestId && latest.status == "error") {
            throw ConfirmedBackendFailure(latest.error ?: "The earlier render failed on this backend")
        }
        if (latest.status == "none" && latest.promptId == null &&
            (latest.requestId == null || latest.requestId == job.requestId)) {
            // The bridge's explicit absence response is {"status":"none"};
            // missing fields/defaults or another request's reply are not proof.
            return null
        }
        val promptId = latest.promptId?.takeIf { it.isNotBlank() }
        if (latest.status in RECOVERABLE_STATUSES && latest.requestId == job.requestId &&
            promptId != null) return promptId
        throw TransientApiException("Could not verify the earlier render reply. Checking again…")
    }

    private fun storePromptId(connectionId: String, promptId: String): String {
        // commit(): if the process dies now, the next start must reuse this
        // prompt instead of submitting a second copy of the same render.
        report(connectionId, durable = true) { it.copy(promptId = promptId, message = "Queued") }
        return promptId
    }

    /**
     * Follows a running prompt.
     *
     * The history endpoint stays the source of truth, but the websocket removes
     * the poll interval from the visible latency and lets the interval grow: a
     * ten-minute render used to cost roughly six hundred HTTP round trips per
     * backend, which at three backends was the app's single largest source of
     * network traffic.
     */
    private suspend fun follow(
        config: ConnectionConfig,
        connectionId: String,
        promptId: String,
        parameters: GenerationParameters,
        deadlineMillis: Long,
        wake: Channel<Unit>,
        terminalWake: Channel<Unit>,
        socketAlive: () -> Boolean,
        backendFailure: () -> String?
    ): List<GeneratedImage> {
        var transientSince = 0L
        var consecutiveFailures = 0

        while (System.currentTimeMillis() < deadlineMillis) {
            try {
                val remaining = (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L)
                val snapshot = withTimeoutOrNull(remaining) {
                    historyUntilTerminal(config, promptId, terminalWake)
                } ?: throw ApiException(TIMEOUT_MESSAGE)
                transientSince = 0L
                consecutiveFailures = 0

                if (snapshot.images.isNotEmpty()) {
                    return snapshot.images.mapIndexed { index, descriptor ->
                        toImage(connectionId, promptId, index, descriptor, parameters)
                    }
                }
                if (snapshot.failed) throw ConfirmedBackendFailure(
                    backendFailure() ?: "ComfyUI reported an error while rendering. Check the Colab output."
                )
                if (snapshot.completed) throw ConfirmedBackendFailure("Finished without producing an image")

                val elapsed = System.currentTimeMillis() - (job(connectionId)?.startedAtMillis ?: 0L)
                val interval = pollInterval(elapsed, socketAlive())
                // The socket, when present, cuts this wait short the moment the
                // backend says it is done.
                val wait = min(interval, (deadlineMillis - System.currentTimeMillis()).coerceAtLeast(0L))
                withTimeoutOrNull(wait) { wake.receive() }
            } catch (transient: TransientApiException) {
                consecutiveFailures += 1
                val now = System.currentTimeMillis()
                if (transientSince == 0L) transientSince = now

                if (now - transientSince > TRANSIENT_BUDGET_MS) {
                    // One dead tunnel must not hold the batch open for the full
                    // deadline while its siblings have already finished.
                    throw ApiException(
                        "Lost contact with Colab or its tunnel. Check the runtime and current server URL before retrying."
                    )
                }

                val backoff = min(1_000L shl min(consecutiveFailures - 1, 3), MAX_BACKOFF_MS)
                report(connectionId) { it.copy(message = "Reconnecting…") }
                // A terminal frame should also cut short a transient backoff.
                // Progress/disconnect frames retain the normal retry spacing.
                val wait = min(backoff, (deadlineMillis - now).coerceAtLeast(0L))
                withTimeoutOrNull(wait) { terminalWake.receive() }
            }
        }
        throw ApiException(TIMEOUT_MESSAGE)
    }

    /**
     * A finished socket frame can arrive while an older history GET is stuck
     * at the tunnel. Cancel that read once, then ask history again immediately.
     * Socket frames never provide the image list or establish completion.
     */
    private suspend fun historyUntilTerminal(
        config: ConnectionConfig,
        promptId: String,
        terminalWake: Channel<Unit>
    ): ComfyApi.HistorySnapshot {
        // A frame observed before starting this request already makes it the
        // fresh confirmation read; do not cancel and duplicate it unnecessarily.
        if (terminalWake.tryReceive().isSuccess) return api.history(config, promptId)

        val selected = coroutineScope {
            val history = async<Result<ComfyApi.HistorySnapshot>> {
                try {
                    Result.success(api.history(config, promptId))
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (error: Exception) {
                    // Keep a failed read in the select instead of having an
                    // async child cancel its parent before a terminal wake wins.
                    Result.failure(error)
                }
            }
            try {
                select<Result<ComfyApi.HistorySnapshot>?> {
                    history.onAwait { it }
                    terminalWake.onReceive { null }
                }
            } finally {
                history.cancel()
            }
        }
        return selected?.getOrThrow() ?: api.history(config, promptId)
    }

    private fun pollInterval(elapsedMillis: Long, socketAlive: Boolean): Long = when {
        socketAlive -> SOCKET_POLL_INTERVAL_MS
        elapsedMillis < 10_000L -> 1_000L
        elapsedMillis < 60_000L -> 2_000L
        else -> 3_000L
    }

    private fun toImage(
        connectionId: String,
        promptId: String,
        index: Int,
        descriptor: ImageDescriptor,
        parameters: GenerationParameters
    ): GeneratedImage {
        val current = job(connectionId)
        return GeneratedImage(
            id = "$connectionId-$promptId-$index",
            connectionId = connectionId,
            connectionName = current?.connectionName.orEmpty(),
            promptId = promptId,
            descriptor = descriptor,
            prompt = parameters.prompt,
            negativePrompt = parameters.negativePrompt,
            model = parameters.model,
            lora = parameters.lora,
            loraStrength = parameters.loraStrength,
            negativePromptRecorded = true,
            width = parameters.width,
            height = parameters.height,
            steps = parameters.steps,
            cfg = parameters.cfg,
            sampler = parameters.sampler,
            scheduler = parameters.scheduler,
            seed = current?.seed ?: parameters.seed,
            speedExtras = parameters.speedExtras
        )
    }

    private fun skip(connectionId: String, reason: String) {
        report(connectionId, durable = true) {
            it.copy(
                state = BackendRunState.SKIPPED,
                message = reason,
                failureReason = reason,
                recoveryRequired = it.recoveryRequired || it.submissionAttempted || it.promptId != null,
                finishedAtMillis = System.currentTimeMillis()
            )
        }
    }

    private fun fail(connectionId: String, reason: String, confirmed: Boolean = false) {
        report(connectionId, durable = true) {
            it.copy(
                state = BackendRunState.FAILED,
                message = reason,
                failureReason = reason,
                recoveryRequired = !confirmed && (it.recoveryRequired || it.submissionAttempted || it.promptId != null),
                finishedAtMillis = System.currentTimeMillis()
            )
        }
    }

    private fun job(connectionId: String): BackendJob? =
        store.current()?.takeIf { it.batchId == batchId }?.job(connectionId)

    private fun report(connectionId: String, durable: Boolean = false, transform: (BackendJob) -> BackendJob) {
        val changed = store.updateJob(batchId, connectionId, durable) { current ->
            // WebSocket callbacks can arrive after a terminal history result.
            // They may add progress to an active job, but never reopen or
            // overwrite a completed/failed/skipped target.
            if (current.state.isTerminal) current else transform(current)
        }
        if (changed != null) onChanged()
    }

    private companion object {
        const val TIMEOUT_MINUTES = 10
        const val TIMEOUT_MESSAGE = "Stopped monitoring after $TIMEOUT_MINUTES minutes. " +
            "Check Colab before retrying; an accepted render may still finish."
        const val MAX_BACKOFF_MS = 8_000L
        const val SOCKET_POLL_INTERVAL_MS = 5_000L
        const val TRANSIENT_BUDGET_MS = 90_000L
        const val RECOVERY_ATTEMPTS = 6
        const val RECOVERY_INTERVAL_MS = 2_000L
        val RECOVERABLE_STATUSES = setOf("pending", "done", "unknown")
    }
}
