package app.phonestudio.generation

import java.net.URLEncoder
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.BackendRunState

/** A Stop belongs to its saved batch. An old runner or a legacy unbound action cannot authorize cancelling another one. */
internal object CancellationPolicy {
    fun targetsCurrent(expectedBatchId: String?, currentBatchId: String?, blocksNewWork: Boolean): Boolean =
        blocksNewWork && !expectedBatchId.isNullOrBlank() && expectedBatchId == currentBatchId

    fun needsLegacyStop(job: BackendJob): Boolean =
        job.state != BackendRunState.COMPLETE || job.recoveryRequired

    fun stoppedLegacyJob(job: BackendJob, finishedAtMillis: Long): BackendJob {
        if (!needsLegacyStop(job)) return job
        return job.copy(
            // Saved partial images remain available, but uncertainty must remain eligible for recovery.
            state = if (job.images.isEmpty()) BackendRunState.SKIPPED else BackendRunState.FAILED,
            message = "Stopped waiting; accepted work remains saved",
            recoveryRequired = job.recoveryRequired || job.submissionAttempted || job.promptId != null,
            failureReason = "Stopped waiting; recover accepted work before submitting again.",
            finishedAtMillis = finishedAtMillis
        )
    }

    /** PendingIntent ignores extras when comparing identities, so batch identity must also be in Intent.data. */
    fun pendingIntentIdentity(batchId: String): String {
        require(batchId.isNotBlank()) { "A Stop action needs a saved batch ID." }
        return "phone-studio-cancel:" + URLEncoder.encode(batchId, Charsets.UTF_8.name())
    }
}
