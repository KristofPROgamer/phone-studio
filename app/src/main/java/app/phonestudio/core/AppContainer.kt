package app.phonestudio.core

import android.content.Context
import app.phonestudio.data.local.AppPreferences
import app.phonestudio.data.local.ConnectionRepository
import app.phonestudio.data.local.GenerationBatchStore
import app.phonestudio.data.remote.ComfyApi
import app.phonestudio.data.remote.ComfyEventStream
import app.phonestudio.data.remote.StudioHttp
import app.phonestudio.data.remote.RouterApi
import app.phonestudio.generation.GenerationOrchestrator

/**
 * One place where the app's long-lived objects are built.
 *
 * Replaces the previous mix of `object` singletons with lazy `lateinit` state
 * and `initialize(context)` calls sprinkled through the view model and the
 * service. Nothing here needs an Activity, so nothing here can leak one, and
 * every collaborator can be swapped in a test.
 */
class AppContainer(context: Context) {

    /** The application context, so a view model can start a service without holding an Activity. */
    val appContext: Context = context.applicationContext

    val connections: ConnectionRepository by lazy { ConnectionRepository(appContext) }

    val preferences: AppPreferences by lazy { AppPreferences(appContext) }

    val batchStore: GenerationBatchStore by lazy { GenerationBatchStore(appContext) }

    /** One connection pool for API calls, websockets and Coil. */
    val http: StudioHttp by lazy { StudioHttp { connections.connections.value } }

    val api: ComfyApi by lazy { ComfyApi(http) }

    val events: ComfyEventStream by lazy { ComfyEventStream(http) }
    val router: RouterApi by lazy { RouterApi(http) }

    val orchestrator: GenerationOrchestrator by lazy {
        GenerationOrchestrator(connections, batchStore, api, events, router)
    }

    val imageExporter: ImageExporter by lazy { ImageExporter(appContext, http) }
    val editFiles: EditFiles by lazy { EditFiles(appContext) }
}

/** Reaches the container from a Service or an Activity without a framework. */
fun Context.studioContainer(): AppContainer =
    (applicationContext as ContainerHolder).container

interface ContainerHolder {
    val container: AppContainer
}

