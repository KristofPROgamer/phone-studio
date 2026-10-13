package app.phonestudio.ui.create

import app.phonestudio.data.model.MaskPoint

/** Fit coordinates are shared by the brush and its overlay, including panorama margins. */
data class MaskViewport(val left: Float, val top: Float, val width: Float, val height: Float) {
    fun normalize(x: Float, y: Float, allowOutside: Boolean = false): MaskPoint? {
        if (width <= 0 || height <= 0) return null
        if (!allowOutside && (x < left || y < top || x > left + width || y > top + height)) return null
        return MaskPoint(((x - left) / width).coerceIn(0f, 1f), ((y - top) / height).coerceIn(0f, 1f))
    }
}

fun fitMaskViewport(width: Float, height: Float, sourceWidth: Int, sourceHeight: Int): MaskViewport {
    if (width <= 0 || height <= 0 || sourceWidth <= 0 || sourceHeight <= 0) return MaskViewport(0f, 0f, 0f, 0f)
    val ratio = sourceWidth.toFloat() / sourceHeight
    val fittedWidth = minOf(width, height * ratio)
    val fittedHeight = fittedWidth / ratio
    return MaskViewport((width - fittedWidth) / 2, (height - fittedHeight) / 2, fittedWidth, fittedHeight)
}
