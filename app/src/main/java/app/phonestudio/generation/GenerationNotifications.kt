package app.phonestudio.generation

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import app.phonestudio.MainActivity
import app.phonestudio.R
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.BackendRunState
import app.phonestudio.data.model.BatchState
import app.phonestudio.data.model.GenerationBatch

/**
 * Builds the batch notification.
 *
 * Collapsed, it is a rollup plus a progress bar over the number of backends.
 * Expanded, every backend gets its own line, which is the only place per-target
 * state is visible while the app is closed.
 */
class GenerationNotifications(private val context: Context) {

    private val manager = context.getSystemService(NotificationManager::class.java)
    private var lastRenderedText: String? = null
    private var lastUpdateAtMillis = 0L

    fun createChannels() {
        manager.createNotificationChannel(
            NotificationChannel(PROGRESS_CHANNEL, "Rendering", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Live status of each Colab backend during a render."
                setShowBadge(false)
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(DONE_CHANNEL, "Finished renders", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "Tells you when your images are ready."
            }
        )
    }

    fun build(batch: GenerationBatch?): android.app.Notification {
        val title = batch?.summary?.takeIf { it.isNotBlank() } ?: "Preparing your render"
        val lines = batch?.targets?.map(::describe).orEmpty()
        val finished = batch?.targets?.count { it.state.isTerminal } ?: 0
        val total = batch?.targets?.size ?: 0

        val builder = NotificationCompat.Builder(context, PROGRESS_CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(title)
            .setContentText(lines.joinToString("  ·  ").ifBlank { "Working with your Colab GPU" })
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setContentIntent(openApp(REQUEST_OPEN))

        batch?.takeIf { it.blocksNewWork }?.batchId?.takeIf { it.isNotBlank() }?.let { id ->
            builder.addAction(0, "Stop", cancelGeneration(id))
        }

        if (total > 0) builder.setProgress(total, finished, finished == 0 && lines.isNotEmpty())

        if (lines.isNotEmpty()) {
            val style = NotificationCompat.InboxStyle().setBigContentTitle(title)
            lines.take(MAX_LINES).forEach(style::addLine)
            builder.setStyle(style)
        }
        return builder.build()
    }

    /**
     * Skips redundant posts. The previous build rebuilt and re-posted the
     * notification on every status string, several times a second during a
     * render.
     */
    @Synchronized
    fun update(batch: GenerationBatch?, force: Boolean = false) {
        val fingerprint = batch?.targets?.joinToString("|") { "${it.state}:${it.message}:${it.stepsDone}" }
        val now = System.currentTimeMillis()
        if (!force && fingerprint == lastRenderedText) return
        if (!force && now - lastUpdateAtMillis < MIN_UPDATE_INTERVAL_MS) return

        lastRenderedText = fingerprint
        lastUpdateAtMillis = now
        manager.notify(PROGRESS_ID, build(batch))
    }

    fun showCompletion(batch: GenerationBatch) {
        val imageCount = batch.images.count { it.visibleByDefault }
        val unit = if (imageCount == 1) "image" else "images"
        val backends = batch.succeeded.size
        val detail = if (batch.transport == "router") batch.summary else buildString {
            append("$imageCount $unit from $backends ${if (backends == 1) "backend" else "backends"}.")
            batch.unsuccessful.takeIf { it.isNotEmpty() }?.let { failures ->
                append(" ")
                append(failures.joinToString(", ") { "${it.connectionName}: ${it.failureReason ?: "unavailable"}" })
            }
        }

        manager.notify(
            DONE_ID,
            NotificationCompat.Builder(context, DONE_CHANNEL)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle(if (imageCount > 0) "Your images are ready" else "Render did not finish")
                .setContentText(detail)
                .setStyle(NotificationCompat.BigTextStyle().bigText(detail))
                .setAutoCancel(true)
                .setContentIntent(openApp(REQUEST_DONE))
                .build()
        )
    }

    private fun describe(job: BackendJob): String {
        val state = when (job.state) {
            BackendRunState.PENDING -> "waiting"
            BackendRunState.PROBING -> "checking"
            BackendRunState.SUBMITTING -> "submitting"
            BackendRunState.RUNNING -> job.message.ifBlank { "Rendering" }
            BackendRunState.COMPLETE -> "done in ${job.elapsedMillis / 1000}s"
            BackendRunState.FAILED -> job.failureReason ?: "failed"
            BackendRunState.SKIPPED -> job.failureReason ?: "skipped"
        }
        return "${job.connectionName} · $state"
    }

    private fun openApp(requestCode: Int): PendingIntent = PendingIntent.getActivity(
        context,
        requestCode,
        Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    /**
     * Uses getForegroundService so the action actually reaches onStartCommand.
     * The previous build routed cancellation through stopService with an action
     * set on the intent, which Android ignores, so its cancel branch was dead.
     */
    private fun cancelGeneration(batchId: String): PendingIntent = PendingIntent.getForegroundService(
        context,
        REQUEST_CANCEL,
        GenerationService.cancelIntent(context, batchId),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    fun clearProgress() = manager.cancel(PROGRESS_ID)

    companion object {
        const val PROGRESS_ID = 4_202
        const val DONE_ID = 4_203
        const val PROGRESS_CHANNEL = "generation_progress"
        const val DONE_CHANNEL = "generation_complete"

        private const val MAX_LINES = 5
        private const val MIN_UPDATE_INTERVAL_MS = 900L
        private const val REQUEST_OPEN = 0
        private const val REQUEST_DONE = 1
        private const val REQUEST_CANCEL = 2

        @Suppress("unused")
        fun stateLabel(state: BatchState): String = state.name.lowercase()
    }
}
