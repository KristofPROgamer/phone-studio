package app.phonestudio.core

import android.content.ContentValues
import android.content.Context
import android.media.MediaScannerConnection
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import app.phonestudio.data.remote.StudioHttp
import app.phonestudio.data.model.ConnectionConfig
import java.io.File
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Request

/**
 * Copies a finished render into the phone's gallery.
 *
 * The app previously had no way to keep an image: every library entry was a
 * remote `/view` URL that died with the Colab session, so the only copy lived in
 * Drive. The selected connection is captured before the download, keeping its
 * credentials together with the image URL even if saved settings change.
 */
class ImageExporter(private val context: Context, private val http: StudioHttp) {

    suspend fun saveToGallery(config: ConnectionConfig, url: String, displayName: String): Result<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                val request = StudioHttp.authenticated(Request.Builder().url(url).get(), config).build()
                val bytes = http.images.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        throw IOException("The backend returned ${response.code} for this image.")
                    }
                    response.body?.let { StudioHttp.readBoundedImage(it) } ?: throw IOException("That image came back empty.")
                }
                write(bytes, sanitize(displayName))
            }
        }

    private fun write(bytes: ByteArray, name: String): String {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, name)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/$ALBUM")
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("The gallery would not accept a new image.")

            resolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: throw IOException("Could not write into the gallery.")

            values.clear()
            values.put(MediaStore.Images.Media.IS_PENDING, 0)
            resolver.update(uri, values, null, null)
            "Pictures/$ALBUM"
        } else {
            // Pre-Q needs a real file plus the legacy write permission, which the
            // manifest requests with maxSdkVersion 28.
            @Suppress("DEPRECATION")
            val albumDir = File(
                Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
                ALBUM
            )
            if (!albumDir.exists() && !albumDir.mkdirs()) {
                throw IOException("Could not create the Phone Studio album.")
            }
            val target = availableTarget(albumDir, name)
            target.writeBytes(bytes)
            // Index the exact PNG we wrote. insertImage(path, ...) decodes and
            // creates another, recompressed gallery item on these API levels.
            MediaScannerConnection.scanFile(
                context,
                arrayOf(target.absolutePath),
                arrayOf("image/png"),
                null
            )
            "Pictures/$ALBUM"
        }
    }

    private fun availableTarget(directory: File, requestedName: String): File {
        val direct = File(directory, requestedName)
        if (!direct.exists()) return direct

        val extension = requestedName.substringAfterLast('.', missingDelimiterValue = "")
        val stem = if (extension.isBlank()) requestedName else requestedName.removeSuffix(".$extension")
        var index = 2
        while (true) {
            val suffix = if (extension.isBlank()) "_$index" else "_$index.$extension"
            val candidate = File(directory, "$stem$suffix")
            if (!candidate.exists()) return candidate
            index += 1
        }
    }

    private fun sanitize(name: String): String {
        val cleaned = name.replace(Regex("[^A-Za-z0-9._-]"), "_").trim('_', '.').take(80)
        val base = cleaned.ifBlank { "phone_studio_${System.currentTimeMillis()}" }
        return if (base.endsWith(".png", ignoreCase = true)) base else "$base.png"
    }

    private companion object {
        const val ALBUM = "Phone Studio"
    }
}
