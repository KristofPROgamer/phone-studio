package app.phonestudio.ui

import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.ImageDescriptor
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json

/** Only the user's pending actions survive Activity recreation; no credentials or image pixels are stored. */
@Serializable
data class PendingPermissionActions(
    val notificationRequested: Boolean = false,
    val gallerySave: GallerySaveIdentity? = null
) {
    fun requestNotifications() = copy(notificationRequested = true)
    fun clearNotifications() = copy(notificationRequested = false)
    fun requestGallery(image: GeneratedImage) = if (gallerySave != null) this else copy(gallerySave = GallerySaveIdentity.from(image))
    fun clearGallery() = copy(gallerySave = null)

    fun snapshot(): String = json.encodeToString(this)

    companion object {
        private val json = Json { ignoreUnknownKeys = true }
        fun restore(snapshot: String?): PendingPermissionActions {
            if (snapshot.isNullOrBlank() || snapshot.length > 8192) return PendingPermissionActions()
            return runCatching { json.decodeFromString<PendingPermissionActions>(snapshot) }.getOrDefault(PendingPermissionActions())
        }
    }
}

/** Save uses a fresh URL from the current connection and this exact descriptor/asset, even if the library list changes. */
@Serializable
data class GallerySaveIdentity(
    val imageId: String,
    val connectionId: String,
    val descriptor: ImageDescriptor,
    val routerAssetId: String? = null
) {
    fun image() = GeneratedImage(
        id = imageId, connectionId = connectionId, connectionName = "", promptId = "", descriptor = descriptor,
        prompt = "", model = "", width = 0, height = 0, seed = 0L, createdAtMillis = 0L, routerAssetId = routerAssetId
    )

    companion object {
        fun from(image: GeneratedImage) = GallerySaveIdentity(image.id, image.connectionId, image.descriptor, image.routerAssetId)
    }
}
