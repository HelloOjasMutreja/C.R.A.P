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
import java.net.Socket
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

private const val MODEL_SIZE = 480
private const val MODEL_THREADS = 4
private const val FRAMES_PER_LOOK = 4
private const val LOOK_TIMEOUT_MS = 8000L
private const val VISIT_TIMEOUT_MS = 15_000L
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
    private lateinit var network: RoverNetwork
    private lateinit var robot: WifiRobot

    // Created and used only on the analysis thread, which also owns the plant records.
    private var detector: Detector? = null
    private var tagReader: TagReader? = null
    private val tagTracker = TagTracker()
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

    @Volatile
    private var pendingVisit: CompletableFuture<VisitOutcome>? = null

    @Volatile
    private var sightings: List<Sighting> = emptyList()

    @Volatile
    private var frameCount = 0

    @Volatile
    private var missionRunning = false

    @Volatile
    private var missionStop = false

    private val askForCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else verdictText.text = "Camera permission is needed"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        analysis = Executors.newSingleThreadExecutor()
        network = RoverNetwork(this)

        // A robot_host extra points the app at a simulated ESP32 during testing.
        val testHost = intent.getStringExtra("robot_host")
        robot = WifiRobot {
            if (testHost == null) network.connect() else Socket(testHost, ROBOT_PORT)
        }
        analysis.execute {
            book = PlantBook(File(filesDir, "plants.json"))
            engine = DiagnosticEngine(book)
            manager = ActionManager(book, robot)
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
            addView(stopButton(), layoutAt(Gravity.TOP or Gravity.END, 170))
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

    /** Always on screen, and bypasses the analysis thread so it works during a move. */
    private fun stopButton() = Button(this).apply {
        text = "STOP"
        setTextColor(Color.WHITE)
        setBackgroundColor(Color.rgb(190, 30, 30))
        setOnClickListener {
            missionStop = true
            Thread {
                try {
                    robot.stop()
                } catch (error: RobotError) {
                    runOnUiThread { verdictText.text = "Stop failed: ${error.message}" }
                }
            }.start()
        }
    }

    private fun bottomPanel(): View {
        recordText = TextView(this).apply {
            setTextColor(Color.WHITE)
            textSize = 14f
            text = "No visit recorded yet"
        }
        runButton = actionButton("Run on robot") {
            // Cleared here, at the tap: a STOP pressed after this must still cancel the queued move.
            robot.allowMoves()
            act { plant, action -> runOrFinish(plant, action) }
        }
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
                    text = "Start mission"
                    setOnClickListener { startMission() }
                },
            )
            addView(
                Button(this@LiveActivity).apply {
                    text = "Tests"
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

    /** Drives by itself, so it runs on its own thread and a person must stand by with STOP. */
    private fun startMission() {
        if (missionRunning) return
        if (!robot.connected) {
            verdictText.text = "Robot not connected"
            return
        }
        missionRunning = true
        missionStop = false
        robot.allowMoves()
        showMission("Mission started")

        Thread {
            val mission = Mission(
                mover = robot,
                eyes = cameraEyes,
                inspector = missionInspector,
                report = ::showMission,
                stopRequested = { missionStop },
            )
            val result = mission.run()
            missionRunning = false
            Log.i("CRAP", "mission: $result")
            showMission("Mission ${result.ending}: ${result.visited.size} visited, ${result.missed.size} missed")
        }.start()
    }

    private fun showMission(words: String) {
        Log.i("CRAP", "mission: $words")
        runOnUiThread { recordText.text = words }
    }

    private val cameraEyes = object : Eyes {
        /** Enough frames must finish for the tracker to confirm a tag seen after the rover stopped. */
        override fun look(): List<Sighting> {
            val wanted = frameCount + FRAMES_PER_LOOK
            val deadline = System.currentTimeMillis() + LOOK_TIMEOUT_MS
            while (frameCount < wanted) {
                if (missionStop) return emptyList()
                if (System.currentTimeMillis() > deadline) throw RobotError("The camera stopped")
                Thread.sleep(20)
            }
            return sightings
        }
    }

    private val missionInspector = object : Inspector {
        override fun visit(plantId: String): VisitOutcome {
            if (!book.hasPlant(plantId)) book.registerPlant(plantId, "field")
            val result = CompletableFuture<VisitOutcome>()
            pendingVisit = result
            plantToRecord = plantId
            return try {
                result.get(VISIT_TIMEOUT_MS, TimeUnit.MILLISECONDS)
            } catch (error: TimeoutException) {
                throw RobotError("Recording the visit timed out")
            }
        }

        override fun markDone(plantId: String, actionId: String, note: String) {
            manager.markDone(plantId, actionId, note)
        }
    }

    /** Use the plant whose tag is in view, or ask which plant this is. */
    private fun startRecording() {
        if (missionRunning) return
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

        val observation = book.submitObservation(plantId, photo.path, robot.sensors(), detections)
        val result = engine.evaluate(plantId, observation.observationId)
        manager.linkVerification(plantId, observation.observationId)
        val action = manager.propose(plantId)
        shownPlant = plantId
        pendingVisit?.complete(VisitOutcome(result.plantStatus, action?.actionId, action?.actionType))
        pendingVisit = null
        Log.i("CRAP", "visit: $plantId ${result.plantStatus}, ${result.diagnoses.size} diagnoses, ${boxes.size} boxes")
        showRecord()
    }

    /** "Move on" drives forward blindly, so by hand it is only marked done. A person moves the rover. */
    private fun runOrFinish(plantId: String, actionId: String) {
        if (book.getAction(plantId, actionId).actionType == "move_on") {
            manager.markDone(plantId, actionId, "Marked done by the operator; the rover did not move.")
        } else {
            manager.execute(plantId, actionId)
        }
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

        // During a mission the planner owns all movement, so these stay hidden.
        val usable = open.takeUnless { missionRunning }
        val waiting = usable?.status == "awaiting_approval"
        val runWords = if (usable?.actionType == "move_on") "Mark done" else "Run on robot"
        runOnUiThread {
            recordText.text = words
            runButton.text = runWords
            runButton.visibility = if (usable != null && !waiting) View.VISIBLE else View.GONE
            approveButton.visibility = if (waiting) View.VISIBLE else View.GONE
            skipButton.visibility = if (usable != null) View.VISIBLE else View.GONE
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
            val tags = tagTracker.update(reader.readAll(upright))
            val tag = tags.firstOrNull()
            val ms = (System.nanoTime() - start) / 1_000_000
            visiblePlant = tag?.plantId
            sightings = tags.map {
                val spot = finder.locate(it, upright.width, upright.height)
                Sighting(it.plantId, spot.distanceMetres * 100, spot.bearingDegrees)
            }
            frameCount++

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
                val link = if (robot.connected) "Robot connected" else "Robot not connected"
                statsText.text = "${place ?: "No plant tag"}\n$ms ms per frame, ${shown.size} boxes\n$link"
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
        robot.close()
        network.close()
    }
}
