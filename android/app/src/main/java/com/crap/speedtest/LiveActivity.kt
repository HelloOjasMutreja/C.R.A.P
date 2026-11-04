package com.crap.speedtest

import android.Manifest
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Matrix
import android.os.Bundle
import android.util.Log
import android.util.Size
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
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
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private const val MODEL_SIZE = 480
private const val MODEL_THREADS = 4
private const val NOT_SURE = "Not sure"
private const val NEW_PLANT = "New plant"

private val STATUS_WORDS = mapOf(
    "unassessed" to "Not assessed yet",
    "healthy" to "Healthy",
    "suspected_disease" to "Suspected disease",
    "diseased" to "Diseased",
    "uncertain" to "Uncertain, needs a person",
    "needs_reinspection" to "Needs another look",
)

private val ACTION_WORDS = mapOf(
    "inspect_closer" to "Inspect closer",
    "spray_plant" to "Spray plant",
    "reposition_and_retry" to "Reposition and retry",
    "request_review" to "Ask a person to review",
    "move_on" to "Move on to the next plant",
)

private val OPEN_ACTIONS = setOf("proposed", "awaiting_approval", "approved")

/** Runs the camera, detector, plant records and decisions entirely on the phone. */
class LiveActivity : ComponentActivity() {

    private lateinit var preview: PreviewView
    private lateinit var boxesView: OverlayView
    private lateinit var verdictText: TextView
    private lateinit var statsText: TextView
    private lateinit var recordText: TextView
    private lateinit var runButton: Button
    private lateinit var approveButton: Button
    private lateinit var skipButton: Button
    private lateinit var analysis: ExecutorService

    // Created and used only on the analysis thread, which also owns the plant records.
    private var detector: Detector? = null
    private var tagReader: TagReader? = null
    private var locator: TagLocator? = null
    private val verdict = LiveVerdict()
    private var frames = 0
    private lateinit var book: PlantBook
    private lateinit var engine: DiagnosticEngine
    private lateinit var manager: ActionManager
    private var shownPlant: String? = null

    @Volatile
    private var visiblePlant: String? = null

    @Volatile
    private var plantToRecord: String? = null

    private val askForCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else verdictText.text = "Camera permission is needed"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        analysis = Executors.newSingleThreadExecutor()
        analysis.execute {
            book = PlantBook(File(filesDir, "plants.json"))
            engine = DiagnosticEngine(book)
            manager = ActionManager(book, SimulatedRobot())
        }

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

        val root = FrameLayout(this).apply {
            fitsSystemWindows = true
            addView(preview)
            addView(boxesView)
            addView(verdictText, layoutAt(Gravity.TOP, 0))
            addView(statsText, layoutAt(Gravity.TOP, 170))
            addView(
                bottomPanel(),
                FrameLayout.LayoutParams(
                    FrameLayout.LayoutParams.MATCH_PARENT,
                    FrameLayout.LayoutParams.WRAP_CONTENT,
                    Gravity.BOTTOM,
                ),
            )
        }
        setContentView(root)

        if (hasCamera()) startCamera() else askForCamera.launch(Manifest.permission.CAMERA)
    }

    private fun bottomPanel(): View {
        recordText = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 14f
            text = "No visit recorded yet"
        }
        runButton = actionButton("Run (simulated)") { act { plant, action -> manager.execute(plant, action) } }
        approveButton = actionButton("Approve") { act { plant, action -> manager.approve(plant, action) } }
        skipButton = actionButton("Skip") { act { plant, action -> manager.reject(plant, action) } }

        val actions = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(runButton)
            addView(approveButton)
            addView(skipButton)
        }
        val main = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(
                Button(this@LiveActivity).apply {
                    text = "Record visit"
                    setOnClickListener { startRecording() }
                },
            )
            addView(
                Button(this@LiveActivity).apply {
                    text = "Speed tests"
                    setOnClickListener { startActivity(Intent(this@LiveActivity, MainActivity::class.java)) }
                },
            )
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.argb(200, 0, 0, 0))
            setPadding(24, 16, 24, 16)
            addView(recordText)
            addView(actions)
            addView(main)
        }
    }

    private fun actionButton(words: String, click: () -> Unit) = Button(this).apply {
        text = words
        visibility = View.GONE
        setOnClickListener { click() }
    }

    private fun layoutAt(gravity: Int, topMargin: Int) =
        FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, gravity)
            .apply { setMargins(16, 16 + topMargin, 16, 16) }

    private fun hasCamera() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    /** Use the plant whose tag is in view, or ask which plant this is. */
    private fun startRecording() {
        val tagged = visiblePlant
        analysis.execute {
            val known = book.listPlants().map { it.plantId }
            runOnUiThread {
                when {
                    tagged == null -> askWhichPlant(known)
                    tagged in known -> plantToRecord = tagged
                    else -> askSpecies(tagged)
                }
            }
        }
    }

    private fun askWhichPlant(known: List<String>) {
        val choices = (known + NEW_PLANT).toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("No tag in view. Which plant?")
            .setItems(choices) { _, which ->
                if (choices[which] == NEW_PLANT) {
                    askSpecies("PLANT_%03d".format(known.size + 1))
                } else {
                    plantToRecord = choices[which]
                }
            }
            .show()
    }

    /** The species comes from a person, because the model mislabels plants it does not know. */
    private fun askSpecies(plantId: String) {
        val choices = (LABELS.map { it.species }.distinct().sorted() + NOT_SURE).toTypedArray()
        AlertDialog.Builder(this)
            .setTitle("What is $plantId?")
            .setItems(choices) { _, which ->
                val species = choices[which].takeUnless { it == NOT_SURE }
                analysis.execute {
                    if (!book.hasPlant(plantId)) book.registerPlant(plantId, "field", species)
                    plantToRecord = plantId
                }
            }
            .show()
    }

    /** Runs on the analysis thread with the frame that was just checked. */
    private fun recordVisit(plantId: String, image: Bitmap, boxes: List<Box>) {
        val folder = File(filesDir, "visits").apply { mkdirs() }
        val photo = File(folder, "${plantId}_${System.currentTimeMillis()}.jpg")
        photo.outputStream().use { image.compress(Bitmap.CompressFormat.JPEG, 90, it) }

        val detections = boxes.map { box ->
            val label = LABELS[box.classId]
            Detection(
                "${label.species} ${label.condition}",
                label.species,
                label.condition,
                label.healthy,
                box.score.toDouble(),
                listOf(box.x1, box.y1, box.x2, box.y2).map { it.toDouble() },
            )
        }

        val observation = book.submitObservation(plantId, photo.path, emptyMap(), detections)
        val result = engine.evaluate(plantId, observation.observationId)
        manager.linkVerification(plantId, observation.observationId)
        manager.propose(plantId)
        shownPlant = plantId
        Log.i("CRAP", "visit: $plantId ${result.plantStatus}, ${result.diagnoses.size} diagnoses, ${boxes.size} boxes")
        showRecord()
    }

    /** Runs a change to the open action, then refreshes the panel. */
    private fun act(change: (String, String) -> Unit) {
        analysis.execute {
            val plantId = shownPlant ?: return@execute
            val action = book.getPlant(plantId).actions.lastOrNull { it.status in OPEN_ACTIONS } ?: return@execute
            try {
                change(plantId, action.actionId)
            } catch (error: IllegalArgumentException) {
                Log.e("CRAP", "Action refused", error)
            }
            showRecord()
        }
    }

    private fun showRecord() {
        val plant = shownPlant?.let(book::getPlant) ?: return
        val action = plant.actions.lastOrNull()
        val open = action?.takeIf { it.status in OPEN_ACTIONS }
        val diagnosis = plant.diagnoses.lastOrNull()

        val words = StringBuilder()
        words.append("${plant.plantId}, ${plant.species ?: "species unknown"}: ")
        words.append(STATUS_WORDS[plant.currentStatus] ?: plant.currentStatus)
        words.append(" (${plant.observations.size} visits)")
        if (diagnosis != null && plant.currentStatus != "healthy") {
            words.append("\n${diagnosis.possibleCondition}: ${diagnosis.status}, ${percent(diagnosis.confidence ?: 0.0)}")
        }
        if (action != null) {
            val name = ACTION_WORDS[action.actionType] ?: action.actionType
            words.append(if (open != null) "\nNext: $name\n${action.reason}" else "\nLast: $name (${action.status})")
            action.result?.let { words.append("\n$it") }
        }

        val waiting = open?.status == "awaiting_approval"
        runOnUiThread {
            recordText.text = words
            runButton.visibility = if (open != null && !waiting) View.VISIBLE else View.GONE
            approveButton.visibility = if (waiting) View.VISIBLE else View.GONE
            skipButton.visibility = if (open != null) View.VISIBLE else View.GONE
        }
    }

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
            visiblePlant = tag?.plantId

            // A known plant's species comes from its record, not from the model's guess.
            val species = tag?.plantId?.takeIf(book::hasPlant)?.let { book.getPlant(it).species }
            val shown = if (species == null) boxes else boxes.filter { LABELS[it.classId].species == species }
            val words = verdict.add(shown)
            val place = tag?.let { "${it.plantId}: ${describe(finder.locate(it, upright.width, upright.height))}" }

            plantToRecord?.let { plantId ->
                plantToRecord = null
                recordVisit(plantId, upright, boxes)
            }

            frames++
            if (frames % 10 == 0) Log.i("CRAP", "live: $ms ms, ${boxes.size} boxes, $words, ${place ?: "no tag"}")

            runOnUiThread {
                boxesView.show(shown, tag, upright.width, upright.height)
                verdictText.text = words
                statsText.text = "${place ?: "No plant tag"}\n$ms ms per frame, ${shown.size} boxes, on phone CPU"
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
