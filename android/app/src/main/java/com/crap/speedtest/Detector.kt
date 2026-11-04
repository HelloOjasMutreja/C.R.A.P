package com.crap.speedtest

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

const val NUM_CLASSES = 29
const val CONFIDENCE = 0.25f
const val OVERLAP = 0.45f

/** How the model runs. NNAPI was dropped because it failed on this model's Split layers. */
enum class Provider { ONNX_CPU, ONNX_XNNPACK, TFLITE_CPU, TFLITE_GPU, TFLITE_GPU_FP32 }

data class Box(
    val classId: Int,
    val score: Float,
    val x1: Float,
    val y1: Float,
    val x2: Float,
    val y2: Float,
)

fun createDetector(context: Context, size: Int, provider: Provider, threads: Int): Detector =
    when (provider) {
        Provider.ONNX_CPU, Provider.ONNX_XNNPACK -> OnnxDetector(context, size, provider, threads)
        Provider.TFLITE_CPU, Provider.TFLITE_GPU, Provider.TFLITE_GPU_FP32 ->
            TfliteDetector(context, size, provider, threads)
    }

/** Shared steps around the model. Mirrors letterbox() and decode() in export_model.py. */
abstract class Detector(val size: Int) : AutoCloseable {

    private val square = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
    protected val pixels = IntArray(size * size)
    private var scale = 1f
    private var padLeft = 0
    private var padTop = 0

    /** Store the image ready for the model. */
    abstract fun prepare(image: Bitmap)

    abstract fun detect(): List<Box>

    /** Fit the image inside a grey square and read its pixels. */
    protected fun letterbox(image: Bitmap) {
        scale = size.toFloat() / max(image.width, image.height)
        val width = (image.width * scale).roundToInt()
        val height = (image.height * scale).roundToInt()
        val left = (size - width) / 2
        val top = (size - height) / 2
        padLeft = left
        padTop = top

        val canvas = Canvas(square)
        canvas.drawColor(Color.rgb(114, 114, 114))
        canvas.drawBitmap(
            image,
            null,
            Rect(left, top, left + width, top + height),
            Paint(Paint.FILTER_BITMAP_FLAG),
        )
        square.getPixels(pixels, 0, size, 0, 0, size, size)
    }

    /** Convert a box from the model's square back to the pixels of the last prepared image. */
    fun toImage(box: Box) = box.copy(
        x1 = (box.x1 - padLeft) / scale,
        y1 = (box.y1 - padTop) / scale,
        x2 = (box.x2 - padLeft) / scale,
        y2 = (box.y2 - padTop) / scale,
    )

    /** The model outputs [4 + classes] rows of [boxes] columns. */
    protected fun decode(data: FloatArray): List<Box> {
        val count = data.size / (4 + NUM_CLASSES)
        val candidates = ArrayList<Box>()

        for (i in 0 until count) {
            var best = 0
            var bestScore = 0f
            for (c in 0 until NUM_CLASSES) {
                val score = data[(4 + c) * count + i]
                if (score > bestScore) {
                    bestScore = score
                    best = c
                }
            }
            if (bestScore >= CONFIDENCE) {
                val cx = data[i]
                val cy = data[count + i]
                val w = data[2 * count + i]
                val h = data[3 * count + i]
                candidates.add(Box(best, bestScore, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            }
        }

        val kept = ArrayList<Box>()
        for (box in candidates.sortedByDescending { it.score }) {
            if (kept.none { it.classId == box.classId && overlap(it, box) > OVERLAP }) {
                kept.add(box)
            }
        }
        return kept
    }

    private fun overlap(a: Box, b: Box): Float {
        val width = max(0f, min(a.x2, b.x2) - max(a.x1, b.x1))
        val height = max(0f, min(a.y2, b.y2) - max(a.y1, b.y1))
        val shared = width * height
        val union = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - shared
        return if (union > 0f) shared / union else 0f
    }

    override fun close() {
        square.recycle()
    }
}

/** Runs the ONNX model on the CPU cores. Takes RGB planes. */
class OnnxDetector(
    context: Context,
    size: Int,
    provider: Provider,
    threads: Int,
) : Detector(size) {

    private val environment = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private val inputName: String
    private val input: FloatBuffer = ByteBuffer
        .allocateDirect(3 * size * size * 4)
        .order(ByteOrder.nativeOrder())
        .asFloatBuffer()
    private val shape = longArrayOf(1, 3, size.toLong(), size.toLong())

    init {
        val options = OrtSession.SessionOptions()
        // Spinning threads fight over this chip's two fast cores.
        options.addConfigEntry("session.intra_op.allow_spinning", "0")
        if (provider == Provider.ONNX_XNNPACK) {
            options.setIntraOpNumThreads(1)
            options.addXnnpack(mapOf("intra_op_num_threads" to threads.toString()))
        } else {
            options.setIntraOpNumThreads(threads)
        }
        val model = context.assets.open("model_$size.onnx").use { it.readBytes() }
        session = environment.createSession(model, options)
        inputName = session.inputNames.first()
    }

    override fun prepare(image: Bitmap) {
        letterbox(image)
        val plane = size * size
        for (i in 0 until plane) {
            val pixel = pixels[i]
            input.put(i, ((pixel shr 16) and 0xFF) / 255f)
            input.put(plane + i, ((pixel shr 8) and 0xFF) / 255f)
            input.put(2 * plane + i, (pixel and 0xFF) / 255f)
        }
    }

    override fun detect(): List<Box> {
        input.rewind()
        return OnnxTensor.createTensor(environment, input, shape).use { tensor ->
            session.run(mapOf(inputName to tensor)).use { result ->
                val buffer = (result.get(0) as OnnxTensor).floatBuffer
                val data = FloatArray(buffer.remaining())
                buffer.get(data)
                decode(data)
            }
        }
    }

    override fun close() {
        session.close()
        super.close()
    }
}
