package com.crap.speedtest

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Matrix
import android.os.Bundle
import android.util.Log
import android.util.Size
import android.view.Gravity
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private const val MODEL_SIZE = 480
private const val MODEL_THREADS = 4

/** Runs the camera and the detector entirely on the phone. */
class LiveActivity : ComponentActivity() {

    private lateinit var preview: PreviewView
    private lateinit var boxesView: OverlayView
    private lateinit var verdictText: TextView
    private lateinit var statsText: TextView
    private lateinit var analysis: ExecutorService

    // Created and used only on the analysis thread.
    private var detector: Detector? = null
    private var tagReader: TagReader? = null
    private var locator: TagLocator? = null
    private val verdict = LiveVerdict()
    private var frames = 0

    private val askForCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else verdictText.text = "Camera permission is needed"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        analysis = Executors.newSingleThreadExecutor()

        preview = PreviewView(this).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
        boxesView = OverlayView(this)
        verdictText = TextView(this).apply {
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.argb(170, 0, 0, 0))
            textSize = 20f
            setPadding(32, 24, 32, 24)
            text = "Loading the model..."
        }
        statsText = TextView(this).apply {
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.argb(120, 0, 0, 0))
            textSize = 13f
            setPadding(24, 10, 24, 10)
        }
        val testsButton = Button(this).apply {
            text = "Speed tests"
            setOnClickListener { startActivity(Intent(this@LiveActivity, MainActivity::class.java)) }
        }

        val root = FrameLayout(this).apply {
            fitsSystemWindows = true
            addView(preview)
            addView(boxesView)
            addView(verdictText, layoutAt(Gravity.TOP, 0))
            addView(statsText, layoutAt(Gravity.TOP, 170))
            addView(testsButton, layoutAt(Gravity.BOTTOM or Gravity.END, 0))
        }
        setContentView(root)

        if (hasCamera()) startCamera() else askForCamera.launch(Manifest.permission.CAMERA)
    }

    private fun layoutAt(gravity: Int, topMargin: Int) =
        FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, gravity)
            .apply { setMargins(16, 16 + topMargin, 16, 16) }

    private fun hasCamera() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun startCamera() {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            val provider = future.get()
            val screen = Preview.Builder().build().also { it.surfaceProvider = preview.surfaceProvider }

            val frames = ImageAnalysis.Builder()
                .setResolutionSelector(
                    ResolutionSelector.Builder()
                        .setResolutionStrategy(
                            ResolutionStrategy(
                                Size(640, 480),
                                ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER,
                            ),
                        )
                        .build(),
                )
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                .build()
            frames.setAnalyzer(analysis) { image -> analyze(image) }

            provider.unbindAll()
            provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, screen, frames)
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(image: ImageProxy) {
        try {
            val model = detector ?: createDetector(this, MODEL_SIZE, Provider.ONNX_XNNPACK, MODEL_THREADS)
                .also { detector = it }
            val reader = tagReader ?: TagReader().also { tagReader = it }
            val finder = locator ?: TagLocator.forBackCamera(this).also { locator = it }
            val upright = uprightBitmap(image)

            val start = System.nanoTime()
            model.prepare(upright)
            val boxes = model.detect().map(model::toImage)
            val tag = reader.read(upright)
            val ms = (System.nanoTime() - start) / 1_000_000
            val words = verdict.add(boxes)
            val place = tag?.let { "${it.plantId}: ${describe(finder.locate(it, upright.width, upright.height))}" }

            frames++
            if (frames % 10 == 0) Log.i("CRAP", "live: $ms ms, ${boxes.size} boxes, $words, ${place ?: "no tag"}")

            runOnUiThread {
                boxesView.show(boxes, tag, upright.width, upright.height)
                verdictText.text = words
                statsText.text = "${place ?: "No plant tag"}\n$ms ms per frame, ${boxes.size} boxes, on phone CPU"
            }
        } catch (error: Throwable) {
            Log.e("CRAP", "Live detection failed", error)
            runOnUiThread { verdictText.text = "Detection failed: ${error.message}" }
        } finally {
            image.close()
        }
    }

    private fun uprightBitmap(image: ImageProxy): Bitmap {
        val raw = image.toBitmap()
        val degrees = image.imageInfo.rotationDegrees
        if (degrees == 0) return raw
        val turn = Matrix().apply { postRotate(degrees.toFloat()) }
        return Bitmap.createBitmap(raw, 0, 0, raw.width, raw.height, turn, true)
    }

    override fun onDestroy() {
        super.onDestroy()
        analysis.execute { detector?.close() }
        analysis.shutdown()
    }
}
