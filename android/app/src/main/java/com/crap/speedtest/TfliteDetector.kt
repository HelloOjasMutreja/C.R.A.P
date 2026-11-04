package com.crap.speedtest

import android.content.Context
import android.graphics.Bitmap
import org.tensorflow.lite.Interpreter
import org.tensorflow.lite.gpu.GpuDelegate
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.channels.FileChannel

/** Runs the TensorFlow Lite model on the GPU or CPU. Takes interleaved RGB pixels. */
class TfliteDetector(
    context: Context,
    size: Int,
    provider: Provider,
    threads: Int,
) : Detector(size) {

    private val interpreter: Interpreter
    private val gpu: GpuDelegate?
    private val input: ByteBuffer = ByteBuffer
        .allocateDirect(size * size * 3 * 4)
        .order(ByteOrder.nativeOrder())

    // The output is [1, 4 + classes, boxes], and a 480 input gives 4725 boxes.
    private val boxCount = (size / 8) * (size / 8) + (size / 16) * (size / 16) + (size / 32) * (size / 32)
    private val outputSize = (4 + NUM_CLASSES) * boxCount
    private val output: ByteBuffer = ByteBuffer
        .allocateDirect(outputSize * 4)
        .order(ByteOrder.nativeOrder())

    init {
        val options = Interpreter.Options()
        if (provider != Provider.TFLITE_CPU) {
            val halfPrecision = provider == Provider.TFLITE_GPU
            val delegate = GpuDelegate(GpuDelegate.Options().apply { setPrecisionLossAllowed(halfPrecision) })
            options.addDelegate(delegate)
            gpu = delegate
        } else {
            options.setNumThreads(threads)
            gpu = null
        }

        val file = context.assets.openFd("model_$size.tflite")
        val model = FileInputStream(file.fileDescriptor).use { stream ->
            stream.channel.map(FileChannel.MapMode.READ_ONLY, file.startOffset, file.declaredLength)
        }
        interpreter = Interpreter(model, options)
    }

    override fun prepare(image: Bitmap) {
        letterbox(image)
        val floats = input.asFloatBuffer()
        for (i in pixels.indices) {
            val pixel = pixels[i]
            floats.put(3 * i, ((pixel shr 16) and 0xFF) / 255f)
            floats.put(3 * i + 1, ((pixel shr 8) and 0xFF) / 255f)
            floats.put(3 * i + 2, (pixel and 0xFF) / 255f)
        }
    }

    override fun detect(): List<Box> {
        input.rewind()
        output.rewind()
        interpreter.run(input, output)
        output.rewind()
        val data = FloatArray(outputSize)
        output.asFloatBuffer().get(data)
        return decode(data)
    }

    override fun close() {
        interpreter.close()
        gpu?.close()
        super.close()
    }
}
