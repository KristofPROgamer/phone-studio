package app.phonestudio

import android.app.Application
import app.phonestudio.core.AppContainer
import app.phonestudio.core.ContainerHolder
import coil.ImageLoader
import coil.ImageLoaderFactory
import coil.disk.DiskCache
import coil.memory.MemoryCache

class StudioApplication : Application(), ContainerHolder, ImageLoaderFactory {

    override val container: AppContainer by lazy { AppContainer(this) }

    /**
     * Coil shares the app's OkHttp client, so `/view` requests reuse the same
     * connection pool as the API calls and pick up tunnel credentials from the
     * auth interceptor. Previously Coil ran its own client and every composable
     * rebuilt an auth header by hand.
     */
    override fun newImageLoader(): ImageLoader = ImageLoader.Builder(this)
        .okHttpClient { container.http.images }
        .memoryCache {
            MemoryCache.Builder(this)
                .maxSizePercent(0.25)
                .build()
        }
        .diskCache {
            DiskCache.Builder()
                .directory(cacheDir.resolve("image_cache"))
                .maxSizeBytes(192L * 1024 * 1024)
                .build()
        }
        // ngrok sends no-store headers that would otherwise defeat caching for
        // images that never change once written.
        .respectCacheHeaders(false)
        .crossfade(180)
        .build()
}

