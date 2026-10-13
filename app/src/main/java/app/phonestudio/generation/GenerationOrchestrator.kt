package app.phonestudio.generation

import app.phonestudio.data.local.ConnectionRepository
import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.BackendRunState
import app.phonestudio.data.model.ConnectionConfig
import app.phonestudio.data.model.GenerationBatch
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.Seeds
import app.phonestudio.data.model.EditDraft
import app.phonestudio.data.remote.RouterApi
import app.phonestudio.data.remote.ComfyApi
import app.phonestudio.data.remote.ComfyEventStream
import java.util.UUID
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.supervisorScope

/**
 * Turns one Generate press into N concurrent renders.
 *
 * Concurrency lives here rather than in the service, because Android only needs
 * a single foreground service for a single user-visible operation. Running one
 * service per backend would mean one notification each and would multiply the
 * foreground-service start restrictions for no benefit.
 */
class GenerationOrchestrator(
    private val connections: ConnectionRepository,
    private val store: GenerationBatchStore,
    private val api: ComfyApi,
    private val events: ComfyEventStream,
    private val router: RouterApi
) {

    /**
     * Builds the batch record.
     *
     * The base seed is resolved once, here, and written to the batch. Target 0
     * renders it unchanged, so pinning a seed still means "give me this exact
     * image"; later targets offset from it. One number plus the backend count
     * therefore reproduces the whole batch.
     */
    fun createBatch(
        parameters: GenerationParameters,
        clientId: String,
        targets: List<ConnectionConfig>,
        edit: EditDraft? = null
    ): GenerationBatch {
        val baseSeed = Seeds.resolveBase(parameters.seed)
        val jobs = targets.mapIndexed { index, config ->
            BackendJob(
                connectionId = config.id,
                connectionName = config.displayName,
                requestId = UUID.randomUUID().toString(),
                seed = Seeds.forIndex(baseSeed, index, parameters.varySeedPerBackend)
            )
        }
        return GenerationBatch(
            batchId = UUID.randomUUID().toString(),
            clientId = clientId,
            parameters = parameters.copy(seed = baseSeed),
            targets = jobs,
            transport = if (targets.singleOrNull()?.isRouter == true) "router" else "worker",
            edit = edit
        )
    }

    /** Re-runs only the targets that failed or were skipped, keeping their seeds. */
    fun retryBatch(batch: GenerationBatch): GenerationBatch = if (batch.transport == "router") batch.copy(
        batchId = UUID.randomUUID().toString(), createdAtMillis = System.currentTimeMillis(),
        routerRetry = batch.targets.single().promptId != null,
        targets = batch.targets.map { it.copy(state = BackendRunState.PENDING, failureReason = null, finishedAtMillis = 0) }
    ) else batch.copy(
        batchId = UUID.randomUUID().toString(),
        createdAtMillis = System.currentTimeMillis(),
        targets = batch.targets.map { job ->
            if (job.state == BackendRunState.FAILED || job.state == BackendRunState.SKIPPED) {
                job.copy(
                    state = BackendRunState.PENDING,
                    message = "Waiting",
                    failureReason = null,
                    promptId = null,
                    submissionAttempted = false,
                    requestId = UUID.randomUUID().toString(),
                    stepsDone = 0,
                    stepsTotal = 0,
                    images = emptyList(),
                    startedAtMillis = 0L,
                    finishedAtMillis = 0L
                )
            } else {
                job
            }
        }
    )

    /**
     * Runs every non-terminal target at once.
     *
     * `supervisorScope` is deliberate: a backend that throws must not cancel its
     * siblings. Each child also catches its own failures inside [BackendRunner],
     * so a dead Colab ends up as one SKIPPED row rather than a failed batch.
     */
    suspend fun run(deadlineMillis: Long, onChanged: () -> Unit) {
        val batch = store.current() ?: return
        if (batch.transport == "router") {
            val config = connections.byId(batch.targets.single().connectionId)
            if (config == null) {
                store.updateJob(batch.batchId, batch.targets.single().connectionId, true) {
                    it.copy(state = BackendRunState.FAILED, failureReason = "Restore your router connection to recover this job.")
                }
                onChanged()
                return
            }
            RouterRunner(router, store, batch.batchId, onChanged).run(config, deadlineMillis)
            return
        }
        val runner = BackendRunner(api, events, store, batch.batchId, onChanged)

        supervisorScope {
            batch.targets
                .filter { it.isActive }
                .map { job ->
                    async {
                        val config = connections.byId(job.connectionId)
                        if (config == null || !config.isComplete) {
                            store.updateJob(batch.batchId, job.connectionId, durable = true) {
                                it.copy(
                                    state = BackendRunState.SKIPPED,
                                    message = "Connection was removed",
                                    failureReason = "Connection was removed",
                                    finishedAtMillis = System.currentTimeMillis()
                                )
                            }
                            onChanged()
                            return@async
                        }
                        runner.run(
                            config = config,
                            connectionId = job.connectionId,
                            parameters = batch.parameters,
                            clientId = batch.clientId,
                            deadlineMillis = deadlineMillis
                        )
                    }
                }
                .awaitAll()
        }
    }

    companion object {
        const val BATCH_TIMEOUT_MS = 10 * 60 * 1_000L
        const val ROUTER_TIMEOUT_MS = 30 * 60 * 1_000L
    }

    suspend fun cancelRouter(stopped: GenerationBatch? = store.current()) {
        val batch = stopped?.takeIf { it.transport == "router" } ?: return
        val job = batch.targets.single()
        val config = connections.byId(job.connectionId) ?: return
        val snapshot = job.promptId?.let { router.cancel(config, it) }
            ?: router.recover(config, batch.clientId, job.requestId)?.let { router.cancel(config, it.jobId) }
        store.updateJob(batch.batchId, config.id, true) {
            it.copy(state = if (it.images.isEmpty()) BackendRunState.SKIPPED else BackendRunState.COMPLETE,
                message = "Stopped", routerState = "cancelled", promptId = snapshot?.jobId ?: it.promptId,
                failureReason = "Stopped by you", finishedAtMillis = System.currentTimeMillis())
        }
    }
}
