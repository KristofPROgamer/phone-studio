package app.phonestudio.core

import java.io.File
import java.io.IOException

/** Cleanup applies only to the row/file created by this export, never an existing photo. */
internal object GalleryWrites {
    fun writeOwned(write: () -> Unit, publish: () -> Boolean, discard: () -> Unit) {
        try {
            write()
            if (!publish()) throw IOException("The gallery could not finish saving this image.")
        } catch (error: Exception) {
            runCatching(discard)
            throw error
        }
    }

    /** Atomic reservation avoids two concurrent saves selecting the same filename. */
    fun reserveFile(directory: File, requestedName: String): File {
        val extension = requestedName.substringAfterLast('.', missingDelimiterValue = "")
        val stem = if (extension.isBlank()) requestedName else requestedName.removeSuffix(".$extension")
        var index = 1
        while (true) {
            val name = if (index == 1) requestedName else if (extension.isBlank()) "${stem}_$index" else "${stem}_$index.$extension"
            val candidate = File(directory, name)
            check(candidate.canonicalFile.parentFile == directory.canonicalFile)
            if (candidate.createNewFile()) return candidate
            index++
        }
    }
}
