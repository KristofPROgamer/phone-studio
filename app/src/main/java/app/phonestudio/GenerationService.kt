package app.phonestudio

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import app.phonestudio.data.ApiException
import app.phonestudio.data.ComfyApi
import app.phonestudio.data.GenerationJob
import app.phonestudio.data.GenerationProgress
import app.phonestudio.data.GenerationRunState
import app.phonestudio.data.GenerationTracker
import app.phonestudio.data.StudioPreferences
import app.phonestudio.data.TransientApiException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Owns an interactive render while Phone Studio is backgrounded or removed from
 * Recents. A foreground service is deliberate here: the user starts a visible,
 * potentially multi-minute cloud transfer and gets a live notification for it.
 */
class GenerationService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val api = ComfyApi()
    private var runner: Job? = null

    override fun onCreate() {
        super.onCreate()
        GenerationTracker.initialize(applicationContext)
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_CANCEL) {
            runner?.cancel()
            GenerationTracker.clear(applicationContext)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        val progress = GenerationTracker.current(applicationContext)
        val job = progress.job
        if (!progress.isActive || job == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        showForeground(progress.message)
        if (runner?.isActive != true) {
            runner = serviceScope.launch {
                runGeneration(job)
            }
        }
        // If Android reclaims the process before the job reaches a terminal
        // state, it will redeliver this intent and the persisted prompt ID.
        return START_REDELIVER_INTENT
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        runner?.cancel()
        serviceScope.coroutineContext[Job]?.cancel()
        super.onDestroy()
    }

    private suspend fun runGeneration(initialJob: GenerationJob) {
        var completedImageCount: Int? = null
        try {
            var job = initialJob
            val submission = job.promptId?.let { promptId -> Submission(job, promptId) } ?: submitOrRecover(job)
            job = submission.job
            val promptId = submission.promptId
            if (promptId != job.promptId) {
                job = job.copy(promptId = promptId)
            }
            report(job, GenerationRunState.RUNNING, "Rendering on Colab…")

            val images = api.awaitImages(job.config, promptId, job.parameters) { message ->
                report(job, GenerationRunState.RUNNING, message)
            }
            GenerationTracker.set(
                applicationContext,
                GenerationProgress(
                    status = GenerationRunState.COMPLETE,
                    message = "Image ready.",
                    images = images
                )
            )
            updateNotification("Image ready")
            completedImageCount = images.size
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (error: Exception) {
            GenerationTracker.set(
                applicationContext,
                GenerationProgress(
                    status = GenerationRunState.FAILED,
                    message = error.message ?: "Generation did not finish."
                )
            )
            updateNotification("Generation needs attention")
        } finally {
            stopForeground(STOP_FOREGROUND_REMOVE)
            completedImageCount?.takeIf { StudioPreferences(applicationContext).notifyOnCompletion() }
                ?.let(::showCompletionNotification)
            stopSelf()
        }
    }

    private suspend fun submitOrRecover(initialJob: GenerationJob): Submission {
        // Only recover before sending when this is a re-delivered service: a
        // fresh queue must never attach itself to a previous prompt.
        if (initialJob.submissionAttempted) {
            recoverPromptId(initialJob)?.let { return Submission(initialJob, it) }
        }
        val job = if (initialJob.submissionAttempted) {
            initialJob
        } else {
            initialJob.copy(submissionAttempted = true).also { attemptedJob ->
                report(attemptedJob, GenerationRunState.QUEUED, "Sending the composition to ComfyUI…")
            }
        }

        return try {
            val promptId = api.submitGeneration(job.config, job.parameters, job.clientId, job.requestId) { message ->
                report(job, GenerationRunState.QUEUED, message)
            }
            Submission(job, promptId)
        } catch (error: TransientApiException) {
            // A lost HTTP response is ambiguous: the prompt may already be
            // running. Ask the bridge several times rather than submit a
            // duplicate image just because the phone changed networks.
            report(job, GenerationRunState.QUEUED, "Checking whether Colab received the render…")
            repeat(6) {
                delay(2_000)
                recoverPromptId(job)?.let { promptId -> return Submission(job, promptId) }
            }
            throw ApiException("Could not confirm whether Colab received the render. Reconnect and try again.", error)
        }
    }

    private suspend fun recoverPromptId(job: GenerationJob): String? {
        if (job.requestId.isBlank()) return null
        val latest = runCatching { api.latestJob(job.config, job.clientId, job.requestId) }.getOrNull() ?: return null
        return latest.promptId?.takeIf {
            latest.status in RECOVERABLE_SERVER_STATUSES && latest.requestId == job.requestId
        }
    }

    private fun report(job: GenerationJob, status: GenerationRunState, message: String) {
        GenerationTracker.set(
            applicationContext,
            GenerationProgress(status = status, message = message, job = job)
        )
        updateNotification(message)
    }

    private fun showForeground(message: String) {
        val foregroundType = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notificationFor(message), foregroundType)
    }

    private fun updateNotification(message: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, notificationFor(message))
    }

    private fun notificationFor(message: String) = NotificationCompat.Builder(this, CHANNEL_ID)
        .setSmallIcon(R.drawable.ic_launcher_foreground)
        .setContentTitle("Phone Studio is rendering")
        .setContentText(message.ifBlank { "Working with your Colab GPU…" })
        .setCategory(NotificationCompat.CATEGORY_PROGRESS)
        .setOngoing(true)
        .setOnlyAlertOnce(true)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        )
        .build()

    private fun showCompletionNotification(imageCount: Int) {
        val imageLabel = if (imageCount == 1) "image" else "images"
        getSystemService(NotificationManager::class.java).notify(
            COMPLETION_NOTIFICATION_ID,
            NotificationCompat.Builder(this, COMPLETION_CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle("Your Phone Studio image is ready")
                .setContentText("$imageCount $imageLabel finished rendering. Tap to view it.")
                .setAutoCancel(true)
                .setContentIntent(
                    PendingIntent.getActivity(
                        this,
                        1,
                        Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
                    )
                )
                .build()
        )
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Image generation",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = "Shows the progress of an active Phone Studio render."
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(
                COMPLETION_CHANNEL_ID,
                "Finished renders",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply {
                description = "Alerts you when a Phone Studio image is ready."
            }
        )
    }

    companion object {
        private const val ACTION_CANCEL = "app.phonestudio.action.CANCEL_GENERATION"
        private const val CHANNEL_ID = "generation_progress"
        private const val COMPLETION_CHANNEL_ID = "generation_complete"
        private const val NOTIFICATION_ID = 4_202
        private const val COMPLETION_NOTIFICATION_ID = 4_203
        private val RECOVERABLE_SERVER_STATUSES = setOf("pending", "done", "unknown")

        private data class Submission(val job: GenerationJob, val promptId: String)

        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context.applicationContext,
                Intent(context.applicationContext, GenerationService::class.java)
            )
        }

        fun cancel(context: Context) {
            GenerationTracker.clear(context.applicationContext)
            context.applicationContext.stopService(
                Intent(context.applicationContext, GenerationService::class.java).setAction(ACTION_CANCEL)
            )
        }
    }
}
