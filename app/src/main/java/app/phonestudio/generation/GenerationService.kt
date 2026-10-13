package app.phonestudio.generation

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.net.Uri
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.phonestudio.core.AppContainer
import app.phonestudio.core.studioContainer
import app.phonestudio.data.local.BatchStorageException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Owns a batch while Phone Studio is backgrounded or swiped away.
 *
 * Still one service, now driving several backends at once. It does not know how
 * many: it starts the orchestrator, mirrors the batch store into the
 * notification, and stops once every target is terminal.
 */
class GenerationService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private lateinit var container: AppContainer
    private lateinit var notifications: GenerationNotifications
    private var runner: Job? = null
    private var runningBatchId: String? = null
    private var latestStartId: Int = 0
    private var cancellation: Job? = null
    private var cancellingBatchId: String? = null

    override fun onCreate() {
        super.onCreate()
        container = applicationContext.studioContainer()
        notifications = GenerationNotifications(applicationContext)
        notifications.createChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Every path calls startForeground first. Anything started with
        // startForegroundService must, even when it is about to stop itself.
        startForegroundCompat()
        latestStartId = startId

        val currentBatch = container.batchStore.current()
        if (intent?.action == ACTION_CANCEL &&
            CancellationPolicy.targetsCurrent(intent.getStringExtra(EXPECTED_BATCH), currentBatch?.batchId, currentBatch?.blocksNewWork == true)) {
            val original = requireNotNull(currentBatch)
            if (cancellation?.isActive == true && cancellingBatchId == original.batchId) return START_NOT_STICKY
            val previousRunner = runner
            runningBatchId = null
            previousRunner?.cancel()
            runner = null
            cancellingBatchId = original.batchId
            cancellation = serviceScope.launch(start = CoroutineStart.LAZY) {
                previousRunner?.cancelAndJoin()
                // A one-shot POST may have finished while cancellation waited.
                val stopped = container.batchStore.current()?.takeIf { it.batchId == original.batchId } ?: original
                if (stopped.blocksNewWork && stopped.transport == "router") {
                    try { container.orchestrator.cancelRouter(stopped) }
                    catch (_: BatchStorageException) {
                        stopped.targets.forEach { container.batchStore.failInMemory(stopped.batchId, it.connectionId) }
                    }
                    catch (error: Exception) {
                        stopped.targets.forEach { job ->
                            try { container.batchStore.updateJob(stopped.batchId, job.connectionId, true) {
                                it.copy(state = app.phonestudio.data.model.BackendRunState.FAILED,
                                    message = "Stopped waiting; router cancellation was not confirmed", routerState = "cancellation_unconfirmed",
                                    recoveryRequired = it.recoveryRequired || it.submissionAttempted || it.promptId != null,
                                    failureReason = "Cancellation was not confirmed. Reconnect to recover the saved job before submitting again.",
                                    finishedAtMillis = System.currentTimeMillis())
                            } } catch (_: BatchStorageException) { container.batchStore.failInMemory(stopped.batchId, job.connectionId) }
                        }
                    }
                } else if (stopped.blocksNewWork && container.batchStore.current()?.batchId == stopped.batchId) {
                    // Completed peers need no disk transition. A failed stop save
                    // must not turn their finished results into unresolved work.
                    val stopping = stopped.targets.filter(CancellationPolicy::needsLegacyStop)
                    try { stopping.forEach { job -> container.batchStore.updateJob(stopped.batchId, job.connectionId, true) {
                        CancellationPolicy.stoppedLegacyJob(it, System.currentTimeMillis())
                    } } }
                    catch (_: BatchStorageException) { stopping.forEach { container.batchStore.failInMemory(stopped.batchId, it.connectionId) } }
                }
                val owner = currentCoroutineContext()[Job]
                withContext(Dispatchers.Main.immediate) {
                    if (cancellation === owner) {
                        cancellation = null
                        cancellingBatchId = null
                        if (canFinishCancellation(runningBatchId, container.batchStore.current()?.batchId, stopped.batchId)) {
                            stopForeground(STOP_FOREGROUND_REMOVE)
                            notifications.clearProgress()
                            stopSelfResult(latestStartId)
                        }
                    }
                }
            }
            cancellation?.start()
            return START_NOT_STICKY
        }

        // Stale or historical unbound Stops follow ordinary startup handling: resume the current active batch or stop an idle service.
        val batch = container.batchStore.current()
        if (cancellation?.isActive == true && cancellingBatchId == batch?.batchId) return START_NOT_STICKY
        if (batch == null || !batch.isActive) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            notifications.clearProgress()
            stopSelfResult(startId)
            return START_NOT_STICKY
        }

        if (runner?.isActive != true || runningBatchId != batch.batchId) {
            runner?.cancel()
            runningBatchId = batch.batchId
            runner = serviceScope.launch { runBatch(batch.batchId, batch.createdAtMillis) }
        }
        // If Android reclaims the process before every target is terminal, this
        // intent is redelivered and the persisted prompt IDs are reused rather
        // than resubmitted.
        return START_REDELIVER_INTENT
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        runningBatchId = null
        runner?.cancel()
        serviceScope.cancel()
        super.onDestroy()
    }

    private suspend fun runBatch(batchId: String, createdAtMillis: Long) {
        val store = container.batchStore
        try {
            container.orchestrator.run(
                deadlineMillis = createdAtMillis + if (store.current()?.transport == "router")
                    GenerationOrchestrator.ROUTER_TIMEOUT_MS else GenerationOrchestrator.BATCH_TIMEOUT_MS,
                onChanged = { notifications.update(store.current()) }
            )
        } finally {
            // onStartCommand also runs on Main. Moving the check and cleanup to
            // that same serialized thread closes the check-then-stop race where
            // an old runner could tear down a newly started batch.
            withContext(NonCancellable + Dispatchers.Main.immediate) {
                if (runningBatchId == batchId) {
                    runningBatchId = null
                    runner = null
                    val finished = store.current()
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    notifications.clearProgress()

                    if (
                        finished?.batchId == batchId &&
                        !finished.isActive &&
                        container.preferences.notifyOnCompletion
                    ) {
                        notifications.showCompletion(finished)
                    }
                    stopSelfResult(latestStartId)
                }
            }
        }
    }

    private fun startForegroundCompat() {
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        ServiceCompat.startForeground(
            this,
            GenerationNotifications.PROGRESS_ID,
            notifications.build(container.batchStore.current()),
            type
        )
    }

    companion object {
        const val ACTION_CANCEL = "app.phonestudio.action.CANCEL_GENERATION"
        private const val EXPECTED_BATCH = "expected_batch"

        internal fun canFinishCancellation(running: String?, current: String?, stopped: String?): Boolean =
            running == null && (current == null || current == stopped)

        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context.applicationContext,
                Intent(context.applicationContext, GenerationService::class.java)
            )
        }

        /**
         * Delivered through startForegroundService so onStartCommand actually
         * receives the action. stopService silently discards it.
         */
        fun cancel(context: Context) {
            val batchId = context.studioContainer().batchStore.current()?.batchId?.takeIf { it.isNotBlank() } ?: return
            ContextCompat.startForegroundService(
                context.applicationContext,
                cancelIntent(context.applicationContext, batchId)
            )
        }

        internal fun cancelIntent(context: Context, batchId: String): Intent =
            Intent(context.applicationContext, GenerationService::class.java).setAction(ACTION_CANCEL)
                .putExtra(EXPECTED_BATCH, batchId)
                .setData(Uri.parse(CancellationPolicy.pendingIntentIdentity(batchId)))
    }
}
