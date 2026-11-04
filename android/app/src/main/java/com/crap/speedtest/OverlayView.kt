package com.crap.speedtest

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View
import kotlin.math.max

/** Draws detection boxes over the camera preview, which fills the view and crops the edges. */
class OverlayView(context: Context) : View(context) {

    private var boxes: List<Box> = emptyList()
    private var tag: Tag? = null
    private var imageWidth = 1
    private var imageHeight = 1

    private val line = Paint().apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f
        isAntiAlias = true
    }
    private val fill = Paint().apply { style = Paint.Style.FILL }
    private val text = Paint().apply {
        color = Color.WHITE
        textSize = 34f
        isAntiAlias = true
    }

    /** Boxes are in the pixels of an image of the given size. */
    fun show(found: List<Box>, plantTag: Tag?, width: Int, height: Int) {
        boxes = found
        tag = plantTag
        imageWidth = width
        imageHeight = height
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val scale = max(width.toFloat() / imageWidth, height.toFloat() / imageHeight)
        val offsetX = (width - imageWidth * scale) / 2
        val offsetY = (height - imageHeight * scale) / 2

        for (box in boxes) {
            val label = LABELS[box.classId]
            val color = if (label.healthy) Color.rgb(60, 180, 75) else Color.rgb(230, 70, 60)
            val left = offsetX + box.x1 * scale
            val top = offsetY + box.y1 * scale
            val right = offsetX + box.x2 * scale
            val bottom = offsetY + box.y2 * scale

            line.color = color
            canvas.drawRect(left, top, right, bottom, line)

            val words = "${label.species}: ${label.condition} ${(box.score * 100).toInt()}%"
            val tagTop = max(0f, top - 44f)
            fill.color = color
            canvas.drawRect(left, tagTop, left + text.measureText(words) + 16f, tagTop + 44f, fill)
            canvas.drawText(words, left + 8f, tagTop + 33f, text)
        }

        tag?.let { found ->
            line.color = Color.CYAN
            val p = found.corners
            for (i in 0 until 4) {
                val next = (i + 1) % 4
                canvas.drawLine(
                    offsetX + p[2 * i] * scale,
                    offsetY + p[2 * i + 1] * scale,
                    offsetX + p[2 * next] * scale,
                    offsetY + p[2 * next + 1] * scale,
                    line,
                )
            }
        }
    }
}
