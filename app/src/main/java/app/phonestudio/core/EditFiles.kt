package app.phonestudio.core

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import androidx.exifinterface.media.ExifInterface
import android.net.Uri
import app.phonestudio.data.model.EditDraft
import app.phonestudio.data.remote.RouterApi
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** App-private copies survive picker grants and process recreation. No broad photo permission is needed. */
class EditFiles(private val context: Context) {
    private val directory get() = File(context.filesDir, "edit-drafts").apply { mkdirs() }
    fun newFile(suffix: String = ".png") = File(directory, UUID.randomUUID().toString() + suffix)

    fun savedFiles(): List<File> = directory.listFiles()?.filter { it.isFile }.orEmpty()

    suspend fun clear(files: List<File>) = withContext(Dispatchers.IO) {
        val target = File(context.filesDir, "edit-drafts")
        check(target.canonicalFile.parentFile == context.filesDir.canonicalFile)
        files.forEach { file -> if (file.canonicalFile.parentFile == target.canonicalFile) file.delete() }
    }

    suspend fun import(uri: Uri): EditDraft = withContext(Dispatchers.IO) {
        val raw = newFile(".source")
        try {
            context.contentResolver.openInputStream(uri)?.use { input -> raw.outputStream().use { output ->
                val buffer = ByteArray(8192)
                var total = 0L
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    total += n
                    require(total <= RouterApi.MAX_UPLOAD) { "Choose an image smaller than 24 MB." }
                    output.write(buffer, 0, n)
                }
            } } ?: error("This image could not be opened. Choose it again.")
            normalize(raw)
        } finally { raw.delete() }
    }

    suspend fun normalize(file: File): EditDraft = withContext(Dispatchers.IO) {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        require(bounds.outWidth >= 8 && bounds.outHeight >= 8) { "Choose a supported photo of at least 8 × 8 pixels." }
        require(bounds.outWidth.toLong() * bounds.outHeight <= 16_000_000) { "Choose an image of 16 megapixels or less." }
        val bitmap = BitmapFactory.decodeFile(file.path) ?: error("This photo format could not be decoded.")
        val orientation = runCatching { ExifInterface(file.path).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1) }.getOrDefault(1)
        val matrix = Matrix().apply {
            when (orientation) {
                2 -> setScale(-1f, 1f)
                3 -> setRotate(180f)
                4 -> setScale(1f, -1f)
                5 -> { setRotate(90f); postScale(-1f, 1f) }
                6 -> setRotate(90f)
                7 -> { setRotate(270f); postScale(-1f, 1f) }
                8 -> setRotate(270f)
            }
        }
        val normalized = if (matrix.isIdentity) bitmap else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, false)
        val target = newFile()
        try {
            target.outputStream().use { check(normalized.compress(Bitmap.CompressFormat.PNG, 100, it)) }
            require(target.length() <= RouterApi.MAX_UPLOAD) { "The lossless source exceeds 24 MB; choose a smaller image." }
            EditDraft(enabled = true, sourcePath = target.path, width = normalized.width, height = normalized.height)
        } catch (error: Exception) { target.delete(); throw error }
        finally { if (normalized !== bitmap) normalized.recycle(); bitmap.recycle() }
    }

    suspend fun mask(draft: EditDraft): String = withContext(Dispatchers.IO) {
        if (draft.strokes.isEmpty()) return@withContext ""
        require(draft.width > 0 && draft.height > 0 && draft.width.toLong() * draft.height <= 16_000_000)
        val bitmap = Bitmap.createBitmap(draft.width, draft.height, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        canvas.drawColor(Color.BLACK)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
        draft.strokes.forEach { stroke ->
            paint.color = if (stroke.erase) Color.BLACK else Color.WHITE
            paint.strokeWidth = stroke.radius * 2 * minOf(draft.width, draft.height)
            val points = stroke.points
            if (points.size == 1) {
                paint.style = Paint.Style.FILL
                canvas.drawCircle(points[0].x * draft.width, points[0].y * draft.height, paint.strokeWidth / 2, paint)
                paint.style = Paint.Style.STROKE
            } else if (points.isNotEmpty()) {
                val path = Path().apply { moveTo(points[0].x * draft.width, points[0].y * draft.height)
                    points.drop(1).forEach { lineTo(it.x * draft.width, it.y * draft.height) } }
                canvas.drawPath(path, paint)
            }
        }
        val target = newFile()
        try { target.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; target.path }
        finally { bitmap.recycle() }
    }
}
