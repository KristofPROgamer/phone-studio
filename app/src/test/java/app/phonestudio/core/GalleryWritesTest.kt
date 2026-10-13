package app.phonestudio.core

import java.io.IOException
import java.nio.file.Files
import java.util.concurrent.Executors
import org.junit.Assert.*
import org.junit.Test

class GalleryWritesTest {
    @Test fun concurrentReservationsKeepExistingPhotoAndProduceDistinctFiles() {
        val directory = Files.createTempDirectory("phone-studio-gallery-test").toFile()
        val existing = directory.resolve("photo.png").apply { writeText("existing-photo") }
        val pool = Executors.newFixedThreadPool(2)
        try {
            val saves = (1..2).map { index -> pool.submit<java.io.File> {
                GalleryWrites.reserveFile(directory, "photo.png").also { it.writeText("save-$index") }
            } }.map { it.get() }
            assertEquals(2, saves.map { it.name }.toSet().size)
            assertEquals(setOf("save-1", "save-2"), saves.map { it.readText() }.toSet())
            assertEquals("existing-photo", existing.readText())
        } finally { pool.shutdownNow(); directory.listFiles().orEmpty().forEach { it.delete() }; directory.delete() }
    }

    @Test fun failedWriteCleansOnlyOwnedEntryAndRetainsOriginalFailure() {
        val original = IOException("test-disk-full")
        var discarded = 0
        try {
            GalleryWrites.writeOwned(write = { throw original }, publish = { fail("No publication after failed write"); false },
                discard = { discarded++; throw IOException("test-cleanup-failure") })
            fail("Expected failed export")
        } catch (error: IOException) { assertSame(original, error) }
        assertEquals(1, discarded)
    }

    @Test fun missingPublicationIsFailureAndSuccessfulPublicationKeepsEntry() {
        var discarded = 0
        try { GalleryWrites.writeOwned({}, { false }, { discarded++ }); fail("Missing row must not claim success") }
        catch (_: IOException) { }
        assertEquals(1, discarded)
        GalleryWrites.writeOwned({}, { true }, { discarded++ })
        assertEquals(1, discarded)
    }
}
