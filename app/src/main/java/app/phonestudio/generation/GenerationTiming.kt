package app.phonestudio.generation

import android.os.SystemClock
import android.util.Log
import app.phonestudio.data.model.GenerationBatch

/** Temporary diagnostics. Set ENABLED to false to silence all timing logs. */
object GenerationTiming {
    const val ENABLED = true
    private const val TAG = "PhoneStudioTiming"
    private const val MAX_REQUESTS = 32

    private data class Trace(
        val startedAt: Long,
        val origin: String,
        var lastAt: Long = startedAt,
        val stages: MutableSet<String> = mutableSetOf()
    )

    private val traces = linkedMapOf<String, Trace>()

    fun now(): Long = SystemClock.elapsedRealtime()

    @Synchronized
    fun start(batch: GenerationBatch, tappedAt: Long) {
        if (!ENABLED) return
        batch.targets.filter { it.isActive }.forEach { job ->
            traces[job.requestId] = Trace(tappedAt, "tap")
            trim()
            mark(job.requestId, "accepted")
        }
    }

    /** A recovered process has no original monotonic tap time: label it explicitly. */
    @Synchronized
    fun resumeIfNeeded(requestId: String) {
        if (!ENABLED || traces.containsKey(requestId)) return
        traces[requestId] = Trace(now(), "resume")
        trim()
        mark(requestId, "resumed")
    }

    @Synchronized
    fun mark(requestId: String, stage: String, promptId: String? = null) {
        if (!ENABLED) return
        val trace = traces[requestId] ?: return
        if (!trace.stages.add(stage)) return
        val current = now()
        // IDs join these lines to Colab timings; never log URLs, prompts or credentials.
        Log.i(TAG, "request=$requestId prompt=${promptId ?: "pending"} stage=$stage " +
            "origin=${trace.origin} elapsed_ms=${current - trace.startedAt} " +
            "since_previous_ms=${current - trace.lastAt}")
        trace.lastAt = current
    }

    private fun trim() {
        while (traces.size > MAX_REQUESTS) traces.remove(traces.keys.first())
    }
}
