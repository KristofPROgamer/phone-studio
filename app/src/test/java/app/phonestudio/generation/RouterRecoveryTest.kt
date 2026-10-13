package app.phonestudio.generation

import app.phonestudio.data.local.*
import app.phonestudio.data.model.*
import app.phonestudio.data.remote.*
import java.io.IOException
import java.util.Collections
import kotlinx.coroutines.runBlocking
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test

/** Real runner/API/store over bounded synthetic HTTP replies; never a rendering-runtime claim. */
class RouterRecoveryTest {
    private val config = ConnectionConfig("router", "Studio", "https://synthetic.invalid",
        tunnelUser = "studio", tunnelPassword = "synthetic-pass", studioToken = "synthetic-token", isRouter = true)
    private fun batch(prompt: String? = "accepted", retry: Boolean = true) = GenerationBatch(
        "batch", "phone", GenerationParameters(prompt = "test", model = "model", seed = 1),
        listOf(BackendJob("router", "Studio", "request", 1, promptId = prompt,
            submissionAttempted = prompt != null, studioId = "studio")), transport = "router", routerRetry = retry)
    private fun snapshot(state: String = "complete", workers: List<RouterWorker> = listOf(RouterWorker(workerId = "w1", state = "complete"))) =
        RouterSnapshot(studioId = "studio", jobId = "accepted", clientId = "phone", requestId = "request",
            revision = if (state == "rendering") 1 else 2, state = state, workers = workers,
            candidates = if (state == "rendering") emptyList() else listOf(RouterCandidate("candidate", "image-hash", "w1", seed = 1,
                width = 768, height = 1024, model = "model")), selection = RouterSelection(status = "disabled"))
    private fun response(request: Request, raw: String, code: Int = 200): Response = Response.Builder()
        .request(request).protocol(Protocol.HTTP_1_1).code(code).message("Synthetic")
        .body(raw.toResponseBody("application/json".toMediaType())).build()
    private fun raw(snapshot: RouterSnapshot) = StudioHttp.json.encodeToString(RouterSnapshot.serializer(), snapshot)
    private val health = """{"ok":true,"service":"phone-studio-router","protocolVersion":2,"studioId":"studio"}"""
    private fun api(calls: MutableList<Request>, handler: (Request) -> Response): RouterApi = RouterApi(StudioHttp(Interceptor { chain ->
        val request = chain.request()
        calls.add(request)
        when (request.url.encodedPath) {
            "/phone-studio/health" -> response(request, health)
            "/phone-studio/v2/ws" -> response(request, "{}", 404)
            else -> handler(request)
        }
    }) { listOf(config) })
    private fun runner(api: RouterApi, store: GenerationBatchStore) = RouterRunner(api, store, store.current()!!.batchId, {}, { _, _, _ -> })
    private fun requests() = Collections.synchronizedList(mutableListOf<Request>())
    private fun deadline() = System.currentTimeMillis() + 10_000

    @Test fun locallyFailedButRemotelyCompletedJobIsCollectedWithoutRetryPost() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        store.commit(batch())
        val calls = requests()
        val api = api(calls) { request -> response(request, raw(snapshot())) }
        runner(api, store).run(config, deadline())
        assertEquals(BackendRunState.COMPLETE, store.current()!!.targets.single().state)
        assertEquals("image-hash", store.current()!!.images.single().routerAssetId)
        assertTrue(calls.none { it.method == "POST" })
        assertFalse(store.current()!!.routerRetry)
    }

    @Test fun acceptedRunningJobIsFollowedWithoutRetryPost() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        store.commit(batch())
        val calls = requests()
        var reads = 0
        val api = api(calls) { request ->
            response(request, raw(snapshot(if (++reads == 1) "rendering" else "complete")))
        }
        runner(api, store).run(config, deadline())
        assertTrue(reads >= 2)
        assertTrue(calls.none { it.method == "POST" })
        assertEquals(BackendRunState.COMPLETE, store.current()!!.targets.single().state)
    }

    @Test fun failedAcceptanceFlagCommitPreventsSubmissionAndSecondDiskWrite() = runBlocking {
        val prefs = MemoryPreferences()
        val store = GenerationBatchStore(prefs)
        store.commit(batch(prompt = null, retry = false))
        val calls = requests()
        // Let the health binding save pass, then fail the actual attempted flag save.
        val transport = api(calls) { request -> response(request, raw(snapshot())) }
        prefs.failAtCommit = 3
        runner(transport, store).run(config, deadline())
        assertTrue(calls.none { it.method == "POST" })
        assertEquals(BackendRunState.FAILED, store.current()!!.targets.single().state)
        assertFalse(GenerationBatchStore(prefs.recreated()).current()!!.targets.single().submissionAttempted)
        assertEquals(3, prefs.commitCount) // Original, binding, failed attempted flag; no second failure write.
    }

    @Test fun acceptedPostWithFailedPromptSaveRecoversSameRequestAfterProcessRecreation() = runBlocking {
        val prefs = MemoryPreferences()
        val store = GenerationBatchStore(prefs)
        store.commit(batch(prompt = null, retry = false))
        val firstCalls = requests()
        val first = api(firstCalls) { request ->
            assertEquals("POST", request.method)
            prefs.failNextCommit = true
            response(request, raw(snapshot()))
        }
        runner(first, store).run(config, deadline())
        assertEquals(1, firstCalls.count { it.method == "POST" })
        assertEquals(BackendRunState.FAILED, store.current()!!.targets.single().state)
        assertTrue(store.current()!!.targets.single().recoveryRequired)
        val restored = GenerationBatchStore(prefs.recreated())
        assertTrue(restored.current()!!.targets.single().submissionAttempted)
        assertNull(restored.current()!!.targets.single().promptId)
        val recoveredCalls = requests()
        val second = api(recoveredCalls) { request ->
            assertEquals("/phone-studio/v2/requests/request", request.url.encodedPath)
            assertEquals("phone", request.url.queryParameter("clientId"))
            response(request, raw(snapshot()))
        }
        runner(second, restored).run(config, deadline())
        assertTrue(recoveredCalls.none { it.method == "POST" })
        assertEquals(BackendRunState.COMPLETE, restored.current()!!.targets.single().state)
        assertEquals("accepted", restored.current()!!.targets.single().promptId)
    }

    @Test fun ambiguousRetryRetainsItsActionKeyAcrossNewLocalBatchOwnership() = runBlocking {
        val prefs = MemoryPreferences()
        val store = GenerationBatchStore(prefs)
        store.commit(batch().copy(routerRetryRequestId = "retry-action"))
        val calls = requests()
        val keys = mutableListOf<String>()
        var attempts = 0
        val partial = snapshot("partial", listOf(RouterWorker(workerId = "w1", state = "complete"), RouterWorker(workerId = "w2", state = "failed")))
        val api = api(calls) { request ->
            if (request.method == "POST") {
                assertTrue(store.current()!!.isActive) // Credentials stay guarded while retry is being sent.
                val body = Buffer().also { request.body!!.writeTo(it) }.readUtf8()
                keys.add(body)
                if (++attempts == 1) throw IOException("Synthetic accepted reply lost")
                response(request, raw(snapshot()))
            } else response(request, raw(partial))
        }
        runner(api, store).run(config, deadline())
        assertEquals("retry-action", store.current()!!.routerRetryRequestId)
        assertTrue(store.current()!!.routerRetry)
        store.commit(store.current()!!.copy(batchId = "new-local-owner", targets = store.current()!!.targets.map { it.copy(state = BackendRunState.PENDING) }))
        runner(api, store).run(config, deadline())
        assertEquals(2, keys.size)
        assertEquals(keys[0], keys[1])
        assertTrue(keys[0].contains("retry-action"))
        assertNull(store.current()!!.routerRetryRequestId)
        assertEquals(BackendRunState.COMPLETE, store.current()!!.targets.single().state)
    }

    @Test fun missingSubmittedRequestCannotBeReportedAsConfirmedCancellation() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        val original = batch(prompt = null, retry = false).copy(targets = batch(prompt = null).targets.map { it.copy(submissionAttempted = true) })
        store.commit(original)
        val calls = requests()
        val api = api(calls) { request -> response(request, "{}", 404) }
        try { runner(api, store).cancel(config, original); fail("Missing acceptance cannot confirm cancellation") }
        catch (_: ApiException) { }
        assertTrue(calls.none { it.method == "POST" })
        assertEquals(original, store.current())
    }

    @Test fun cancellationRejectsDifferentSavedRequestBeforeMutation() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        val original = batch()
        store.commit(original)
        val calls = requests()
        val api = api(calls) { request -> response(request, raw(snapshot().copy(requestId = "different"))) }
        try { runner(api, store).cancel(config, original); fail("Wrong request must not be cancelled") }
        catch (_: ApiException) { }
        assertTrue(calls.none { it.method == "POST" })
        assertEquals(original, store.current())
    }

    @Test fun cancellationRetainsAlreadyCompletedCandidates() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        val original = batch()
        store.commit(original)
        val calls = requests()
        val api = api(calls) { request -> response(request, raw(snapshot())) }
        runner(api, store).cancel(config, original)
        assertEquals(BackendRunState.COMPLETE, store.current()!!.targets.single().state)
        assertEquals("complete", store.current()!!.targets.single().routerState)
        assertEquals(1, store.current()!!.images.size)
    }

    @Test fun uncertainWorkerCancellationPreservesCandidatesAndReportsUnconfirmed() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        val original = batch()
        store.commit(original)
        val calls = requests()
        val api = api(calls) { request -> response(request, raw(if (request.method == "POST")
            snapshot("cancelled", listOf(RouterWorker(workerId = "w1", state = "submission_uncertain"))) else snapshot("rendering"))) }
        try { runner(api, store).cancel(config, original); fail("Uncertain worker is not confirmed stopped") }
        catch (_: ApiException) { }
        assertEquals(BackendRunState.FAILED, store.current()!!.targets.single().state)
        assertEquals("cancellation_unconfirmed", store.current()!!.targets.single().routerState)
        assertFalse(store.current()!!.targets.single().message == "Stopped")
        assertEquals(1, store.current()!!.images.size)
        assertEquals("accepted", store.current()!!.targets.single().promptId)
    }

    @Test fun oldCancellationCannotRemoveNewForegroundOwner() {
        assertFalse(GenerationService.canFinishCancellation("new", "new", "old"))
        assertFalse(GenerationService.canFinishCancellation(null, "new", "old"))
        assertTrue(GenerationService.canFinishCancellation(null, "old", "old"))
        assertTrue(GenerationService.canFinishCancellation(null, null, "old"))
    }

    @Test fun wrongParentStatusIsRejectedBeforeRetryOrCandidatePublication() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        store.commit(batch())
        val calls = requests()
        val api = api(calls) { request -> response(request, raw(snapshot().copy(jobId = "wrong-parent"))) }
        runner(api, store).run(config, deadline())
        assertTrue(calls.none { it.method == "POST" })
        assertEquals("accepted", store.current()!!.targets.single().promptId)
        assertTrue(store.current()!!.images.isEmpty())
        assertTrue(store.current()!!.routerRetry)
    }

    @Test fun wrongRetryReplyCannotConsumePendingActionKey() = runBlocking {
        val store = GenerationBatchStore(MemoryPreferences())
        store.commit(batch().copy(routerRetryRequestId = "saved-action"))
        val calls = requests()
        val failed = snapshot("failed", listOf(RouterWorker(workerId = "w1", state = "failed")))
        val api = api(calls) { request -> response(request, raw(if (request.method == "POST") snapshot().copy(jobId = "wrong-parent") else failed)) }
        runner(api, store).run(config, deadline())
        assertEquals(1, calls.count { it.method == "POST" })
        assertTrue(store.current()!!.routerRetry)
        assertEquals("saved-action", store.current()!!.routerRetryRequestId)
        assertEquals("accepted", store.current()!!.targets.single().promptId)
    }

    @Test fun explicitRetryRetainsUnresolvedLegacyAcceptedIdentity() {
        val accepted = batch().targets.single().copy(state = BackendRunState.FAILED, recoveryRequired = true)
        val original = batch().copy(transport = "worker", routerRetry = false, targets = listOf(accepted))
        val retried = GenerationOrchestrator.retryStoredBatch(original)
        assertNotEquals(original.batchId, retried.batchId)
        val target = retried.targets.single()
        assertEquals(BackendRunState.PENDING, target.state)
        assertEquals(accepted.requestId, target.requestId)
        assertEquals(accepted.promptId, target.promptId)
        assertTrue(target.submissionAttempted)
        assertTrue(target.recoveryRequired)
    }

    @Test fun ambiguousRouterActionSurvivesExplicitRetryWithNewBatchOwner() {
        val original = batch().copy(routerRetryRequestId = "pending-action")
        val retried = GenerationOrchestrator.retryStoredBatch(original)
        assertNotEquals(original.batchId, retried.batchId)
        assertEquals("pending-action", retried.routerRetryRequestId)
        assertEquals(original.targets.single().requestId, retried.targets.single().requestId)
        assertEquals(original.targets.single().promptId, retried.targets.single().promptId)
    }

    @Test fun historicalAcceptedFailuresInferRecoveryWithoutChangingSavedIdentity() {
        val raw = """{"batchId":"legacy","clientId":"phone","parameters":{},"targets":[{"connectionId":"worker","connectionName":"Old worker","requestId":"old-request","seed":1,"state":"FAILED","promptId":"old-prompt","submissionAttempted":true}]}"""
        val restored = StudioHttp.json.decodeFromString(GenerationBatch.serializer(), raw)
        assertTrue(restored.blocksNewWork)
        assertTrue(restored.targets.single().recoveryRequired)
        val retried = GenerationOrchestrator.retryStoredBatch(restored)
        assertEquals("old-prompt", retried.targets.single().promptId)
        assertEquals("old-request", retried.targets.single().requestId)
        assertTrue(retried.targets.single().submissionAttempted)
        val skipped = StudioHttp.json.decodeFromString(BackendJob.serializer(),
            """{"connectionId":"worker","connectionName":"Old","requestId":"old-request","seed":1,"state":"SKIPPED","promptId":"old-prompt"}""")
        assertTrue(skipped.recoveryRequired)
    }

    @Test fun explicitConfirmedFailureAndCompletedOrCancelledLegacyRecordsDoNotInferRecovery() {
        val prefix = """"connectionId":"router","connectionName":"Studio","requestId":"request","seed":1,"promptId":"accepted","submissionAttempted":true"""
        listOf(
            """{$prefix,"state":"FAILED","recoveryRequired":false}""",
            """{$prefix,"state":"COMPLETE"}""",
            """{$prefix,"state":"SKIPPED","routerState":"cancelled"}"""
        ).forEach { raw ->
            assertFalse(StudioHttp.json.decodeFromString(BackendJob.serializer(), raw).recoveryRequired)
        }
        val uncertainWithCandidates = """{$prefix,"state":"COMPLETE","routerState":"partial","routerWorkers":[{"workerId":"w1","state":"complete"},{"workerId":"w2","state":"submission_uncertain"}]}"""
        assertTrue(StudioHttp.json.decodeFromString(BackendJob.serializer(), uncertainWithCandidates).recoveryRequired)
    }
}
