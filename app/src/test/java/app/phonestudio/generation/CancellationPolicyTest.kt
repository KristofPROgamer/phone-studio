package app.phonestudio.generation

import org.junit.Assert.*
import org.junit.Test
import app.phonestudio.data.local.BatchStorageException
import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.local.MemoryPreferences
import app.phonestudio.data.model.BackendJob
import app.phonestudio.data.model.BackendRunState
import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.GenerationBatch
import app.phonestudio.data.model.GenerationParameters
import app.phonestudio.data.model.ImageDescriptor
import app.phonestudio.data.remote.StudioHttp

class CancellationPolicyTest {
    @Test fun aBoundStopCanCancelItsCurrentSavedBatch() {
        assertTrue(CancellationPolicy.targetsCurrent("batch-A", "batch-A", true))
    }

    @Test fun delayedStopForAnEarlierBatchCannotCancelTheNewCurrentBatch() {
        // The same result applies even if the previous runner still belongs to A: only the current saved batch authorizes Stop.
        assertFalse(CancellationPolicy.targetsCurrent("batch-A", "batch-B", true))
    }

    @Test fun historicalUnboundAndEmptyStopActionsCannotCancelCurrentWork() {
        listOf(null, "", " ").forEach { expected ->
            assertFalse(CancellationPolicy.targetsCurrent(expected, "batch-B", true))
        }
    }

    @Test fun aStopWithoutACurrentSavedBatchCannotAuthorizeCancellation() {
        assertFalse(CancellationPolicy.targetsCurrent("batch-A", null, true))
        assertFalse(CancellationPolicy.targetsCurrent("batch-A", "", true))
    }

    @Test fun pendingIntentIdentityIsStableForOneBatchAndDistinctAcrossBatches() {
        assertEquals(CancellationPolicy.pendingIntentIdentity("batch-A"), CancellationPolicy.pendingIntentIdentity("batch-A"))
        assertNotEquals(CancellationPolicy.pendingIntentIdentity("batch-A"), CancellationPolicy.pendingIntentIdentity("batch-B"))
        assertNotEquals(CancellationPolicy.pendingIntentIdentity("a/b"), CancellationPolicy.pendingIntentIdentity("a%2Fb"))
        assertNotEquals(CancellationPolicy.pendingIntentIdentity("a b"), CancellationPolicy.pendingIntentIdentity("a+b"))
    }

    @Test fun stoppingLegacyWorkKeepsCompletedPeersAndRecoversOnlyTheUnfinishedAcceptedTarget() {
        val complete = acceptedJob("worker-1").copy(state = BackendRunState.COMPLETE,
            images = listOf(image("worker-1")), recoveryRequired = false, message = "Ready", finishedAtMillis = 50L)
        val running = acceptedJob("worker-2")
        val stopped = batch(listOf(complete, running)).copy(targets = listOf(
            CancellationPolicy.stoppedLegacyJob(complete, 100L), CancellationPolicy.stoppedLegacyJob(running, 100L)))
        assertEquals(complete, stopped.job("worker-1"))
        assertEquals(listOf("worker-2"), stopped.unsuccessful.map { it.connectionId })
        assertTrue(stopped.blocksNewWork)
        assertEquals(running.promptId, stopped.job("worker-2")!!.promptId)
        assertTrue(stopped.job("worker-2")!!.recoveryRequired)
        val retry = GenerationOrchestrator.retryStoredBatch(stopped)
        assertEquals(complete, retry.job("worker-1"))
        assertEquals(running.requestId, retry.job("worker-2")!!.requestId)
        assertEquals(running.promptId, retry.job("worker-2")!!.promptId)
        val recovered = retry.withJob("worker-2") { it.copy(state = BackendRunState.COMPLETE,
            images = listOf(image("worker-2")), recoveryRequired = false) }
        assertFalse(recovered.blocksNewWork)
    }

    @Test fun matchingStopDoesNotReopenANormallyCompletedBatch() {
        val complete = acceptedJob("worker-1").copy(state = BackendRunState.COMPLETE,
            images = listOf(image("worker-1")), recoveryRequired = false)
        val finished = batch(listOf(complete))
        assertFalse(CancellationPolicy.targetsCurrent(finished.batchId, finished.batchId, finished.blocksNewWork))
    }

    @Test fun previouslyUncertainTargetsWithImagesRemainVisibleAndEligibleForRecovery() {
        val uncertain = acceptedJob("worker-1").copy(state = BackendRunState.COMPLETE,
            images = listOf(image("worker-1")), recoveryRequired = true)
        val stopped = CancellationPolicy.stoppedLegacyJob(uncertain, 100L)
        assertEquals(BackendRunState.FAILED, stopped.state)
        assertTrue(stopped.recoveryRequired)
        assertEquals(uncertain.images, stopped.images)
        assertEquals(uncertain.promptId, stopped.promptId)
        assertEquals(listOf(stopped), batch(listOf(stopped)).unsuccessful)
        val saved = StudioHttp.json.encodeToString(GenerationBatch.serializer(), batch(listOf(stopped)))
        val restored = StudioHttp.json.decodeFromString(GenerationBatch.serializer(), saved)
        val retry = GenerationOrchestrator.retryStoredBatch(restored).targets.single()
        assertEquals(uncertain.requestId, retry.requestId)
        assertEquals(uncertain.promptId, retry.promptId)
        assertEquals(uncertain.images, retry.images)
        assertTrue(retry.recoveryRequired)
        assertEquals(BackendRunState.PENDING, retry.state)
    }

    @Test fun stoppingBeforeAnySubmissionDoesNotCreateAcceptedWorkOrBlockFreshWork() {
        val untouched = acceptedJob("worker-1").copy(state = BackendRunState.PROBING,
            promptId = null, submissionAttempted = false, recoveryRequired = false)
        val stopped = CancellationPolicy.stoppedLegacyJob(untouched, 100L)
        assertEquals(BackendRunState.SKIPPED, stopped.state)
        assertNull(stopped.promptId)
        assertFalse(stopped.submissionAttempted)
        assertFalse(stopped.recoveryRequired)
        assertFalse(batch(listOf(stopped)).blocksNewWork)
    }

    @Test fun failedStopStorageOnlyLeavesUnfinishedTargetsNeedingRecovery() {
        val complete = acceptedJob("worker-1").copy(state = BackendRunState.COMPLETE,
            images = listOf(image("worker-1")), recoveryRequired = false, message = "Ready", finishedAtMillis = 50L)
        val running = acceptedJob("worker-2")
        val preferences = MemoryPreferences()
        val store = GenerationBatchStore(preferences)
        val original = batch(listOf(complete, running))
        store.commit(original)
        val stopping = original.targets.filter(CancellationPolicy::needsLegacyStop)
        assertEquals(listOf(running), stopping)
        preferences.failNextCommit = true
        try {
            store.updateJob(original.batchId, running.connectionId, true) {
                CancellationPolicy.stoppedLegacyJob(it, 100L)
            }
            fail("A failed durable transition must not publish a stopped job")
        } catch (_: BatchStorageException) {
            stopping.forEach { store.failInMemory(original.batchId, it.connectionId) }
        }
        assertEquals(complete, store.current()!!.job(complete.connectionId))
        assertEquals(listOf(running.connectionId), store.current()!!.unsuccessful.map { it.connectionId })
        assertTrue(store.current()!!.job(running.connectionId)!!.recoveryRequired)
        assertEquals(original, GenerationBatchStore(preferences.recreated()).current())
    }

    private fun acceptedJob(id: String) = BackendJob(connectionId = id, connectionName = id, requestId = "request-$id",
        seed = 123L, promptId = "prompt-$id", submissionAttempted = true, state = BackendRunState.RUNNING)

    private fun image(id: String) = GeneratedImage(id = "image-$id", connectionId = id, connectionName = id,
        promptId = "prompt-$id", descriptor = ImageDescriptor("result-$id.png"), prompt = "scene", model = "model.safetensors",
        width = 768, height = 1024, seed = 123L)

    private fun batch(jobs: List<BackendJob>) = GenerationBatch(batchId = "batch-A", clientId = "phone",
        parameters = GenerationParameters(), targets = jobs)
}
