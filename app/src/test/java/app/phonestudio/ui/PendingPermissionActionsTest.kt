package app.phonestudio.ui

import app.phonestudio.data.model.GeneratedImage
import app.phonestudio.data.model.ImageDescriptor
import org.junit.Assert.*
import org.junit.Test

class PendingPermissionActionsTest {
    private fun image(id: String = "image-1", assetId: String? = "asset-1") = GeneratedImage(
        id = id, connectionId = "saved-router", connectionName = "My studio", promptId = "accepted-prompt",
        descriptor = ImageDescriptor("result.png", "saved/subfolder", "output"), prompt = "private-prompt-marker",
        model = "checkpoint.safetensors", width = 768, height = 1024, seed = 123L, routerAssetId = assetId
    )

    @Test fun notificationRequestSurvivesSnapshotAndClearsWithoutRepeating() {
        val restored = PendingPermissionActions.restore(PendingPermissionActions().requestNotifications().snapshot())
        assertTrue(restored.notificationRequested)
        val completed = restored.clearNotifications()
        assertFalse(completed.notificationRequested)
        assertFalse(PendingPermissionActions.restore(completed.snapshot()).notificationRequested)
    }

    @Test fun galleryIdentitySurvivesWithoutLibraryOrOriginalPrompt() {
        val original = image()
        val snapshot = PendingPermissionActions().requestGallery(original).snapshot()
        assertFalse(snapshot.contains("private-prompt-marker"))
        assertFalse(snapshot.contains("accepted-prompt"))
        assertFalse(snapshot.contains("checkpoint.safetensors"))
        val restored = PendingPermissionActions.restore(snapshot).gallerySave!!.image()
        assertEquals(original.id, restored.id)
        assertEquals(original.connectionId, restored.connectionId)
        assertEquals(original.descriptor, restored.descriptor)
        assertEquals(original.routerAssetId, restored.routerAssetId)
        assertEquals("", restored.prompt)
    }

    @Test fun legacyWorkerDescriptorIsPreservedWithoutInventingAnAssetId() {
        val original = image(assetId = null)
        val restored = PendingPermissionActions.restore(PendingPermissionActions().requestGallery(original).snapshot()).gallerySave!!.image()
        assertNull(restored.routerAssetId)
        assertEquals(original.descriptor, restored.descriptor)
    }

    @Test fun independentPermissionCompletionsClearOnlyTheirOwnAction() {
        val pending = PendingPermissionActions().requestNotifications().requestGallery(image())
        assertNotNull(pending.clearNotifications().gallerySave)
        assertFalse(pending.clearNotifications().notificationRequested)
        assertTrue(pending.clearGallery().notificationRequested)
        assertNull(pending.clearGallery().gallerySave)
    }

    @Test fun aSecondSaveCannotReplaceTheImageOfAnOutstandingRequest() {
        val pending = PendingPermissionActions().requestGallery(image("first"))
        assertEquals("first", pending.requestGallery(image("second")).gallerySave!!.imageId)
    }

    @Test fun absentDamagedOrOversizeSnapshotsRestoreNoAction() {
        listOf(null, "", "not-json", "{}trailing", "x".repeat(8193)).forEach {
            assertEquals(PendingPermissionActions(), PendingPermissionActions.restore(it))
        }
    }
}
