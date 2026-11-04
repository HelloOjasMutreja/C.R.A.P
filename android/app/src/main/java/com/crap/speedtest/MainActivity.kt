package com.crap.speedtest

import android.app.Activity
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Typeface
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.util.Log
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.concurrent.thread

private const val WARMUP_RUNS = 3
private const val TIMED_RUNS = 15
private const val COOLDOWN_MS = 2000L

private data class Trial(val provider: Provider, val threads: Int, val size: Int)

private val CPU_PLAN = listOf(
    Trial(Provider.TFLITE_CPU, 2, 480),
    Trial(Provider.TFLITE_CPU, 4, 480),
    Trial(Provider.ONNX_XNNPACK, 2, 480),
    Trial(Provider.ONNX_XNNPACK, 4, 480),
    Trial(Provider.ONNX_XNNPACK, 6, 480),
    Trial(Provider.ONNX_CPU, 2, 480),
    Trial(Provider.ONNX_CPU, 4, 480),
    Trial(Provider.ONNX_CPU, 6, 480),
    Trial(Provider.ONNX_XNNPACK, 2, 320),
    Trial(Provider.ONNX_XNNPACK, 2, 640),
)

// CPU first: full-precision GPU setup can take minutes, so it runs last.
private val GPU_PLAN = listOf(
    Trial(Provider.TFLITE_CPU, 2, 480),
    Trial(Provider.TFLITE_GPU, 1, 480),
    Trial(Provider.TFLITE_GPU_FP32, 1, 480),
)
private const val HEAT_TEST_MINUTES = 20
private const val HEAT_TEST_SIZE = 480
private const val HEAT_LOG_SECONDS = 30

/** Measures how fast the model runs on this phone, and whether it slows down as it heats up. */
class MainActivity : Activity() {

    private lateinit var output: TextView
    private lateinit var scroll: ScrollView
    private lateinit var speedButton: Button
    private lateinit var gpuButton: Button
    private lateinit var heatButton: Button
    private lateinit var stopButton: Button
    private val results = StringBuilder()

    @Volatile
    private var stopRequested = false

    @Volatile
    private var bestProvider = Provider.ONNX_XNNPACK

    @Volatile
    private var bestThreads = 4

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        speedButton = Button(this).apply {
            text = "Run speed test"
            setOnClickListener { runInBackground { speedTest(CPU_PLAN) } }
        }
        // Separate because a GPU driver fault can close the app, which would lose CPU results.
        gpuButton = Button(this).apply {
            text = "Run GPU test"
            setOnClickListener { runInBackground { speedTest(GPU_PLAN) } }
        }
        heatButton = Button(this).apply {
            text = "Run $HEAT_TEST_MINUTES-minute heat test"
            setOnClickListener { runInBackground { heatTest() } }
        }
        stopButton = Button(this).apply {
            text = "Stop"
            isEnabled = false
            setOnClickListener { stopRequested = true }
        }
        val shareButton = Button(this).apply {
            text = "Share results"
            setOnClickListener { shareResults() }
        }

        output = TextView(this).apply {
            typeface = Typeface.MONOSPACE
            textSize = 12f
            setTextIsSelectable(true)
            setPadding(24, 24, 24, 24)
        }
        scroll = ScrollView(this).apply { addView(output) }

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            fitsSystemWindows = true
            setPadding(24, 24, 24, 24)
            addView(speedButton)
            addView(gpuButton)
            addView(heatButton)
            addView(stopButton)
            addView(shareButton)
            addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        setContentView(layout)

        log("Device: ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            log("Chip: ${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}")
        }
        log("Before testing: unplug, stop screen recording, close other apps.")

        // Lets a test be started over USB: adb shell am start ... --es run gpu
        when (intent.getStringExtra("run")) {
            "gpu" -> runInBackground { speedTest(GPU_PLAN) }
            "speed" -> runInBackground { speedTest(CPU_PLAN) }
            "heat" -> runInBackground { heatTest() }
            "tag" -> runInBackground { tagTest() }
        }
    }

    private fun runInBackground(work: () -> Unit) {
        stopRequested = false
        setRunning(true)
        thread {
            try {
                work()
            } catch (error: Throwable) {
                log("Test failed: $error")
            }
            runOnUiThread { setRunning(false) }
        }
    }

    private fun setRunning(running: Boolean) {
        speedButton.isEnabled = !running
        gpuButton.isEnabled = !running
        heatButton.isEnabled = !running
        stopButton.isEnabled = running
    }

    private fun loadSample(): Bitmap = assets.open("sample.png").use { BitmapFactory.decodeStream(it) }

    private fun speedTest(plan: List<Trial>) {
        val image = loadSample()
        var bestMs = Double.MAX_VALUE
        log("")
        log("SPEED TEST: $TIMED_RUNS runs each, prepare + detect, median and slowest")
        log("Battery ${batteryPercent()}%, ${batteryTemperature()} C, thermal ${thermalStatus()}")
        log("The sample image should find 7 or 8 tomato leaves.")

        for ((provider, threads, size) in plan) {
            if (stopRequested) return
            try {
                createDetector(this, size, provider, threads).use { detector ->
                    repeat(WARMUP_RUNS) {
                        detector.prepare(image)
                        detector.detect()
                    }
                    val times = ArrayList<Double>()
                    var found = emptyList<Box>()
                    repeat(TIMED_RUNS) {
                        val start = System.nanoTime()
                        detector.prepare(image)
                        found = detector.detect()
                        times.add((System.nanoTime() - start) / 1e6)
                    }
                    times.sort()
                    val median = times[TIMED_RUNS / 2]
                    val boxes = found.size
                    log(
                        "%-12s %dt %d: %5.0f ms, max %5.0f, %4.1f fps, %d boxes"
                            .format(provider, threads, size, median, times.last(), 1000 / median, boxes),
                    )
                    log("  scores: " + found.joinToString(" ") { "%.2f".format(it.score) })
                    if (size == HEAT_TEST_SIZE && boxes in 7..8 && median < bestMs) {
                        bestMs = median
                        bestProvider = provider
                        bestThreads = threads
                    }
                }
            } catch (error: Throwable) {
                log("%-12s %dt %d: failed (%s)".format(provider, threads, size, error.message))
            }
            // Let the chip cool a little so one test does not slow the next.
            Thread.sleep(COOLDOWN_MS)
        }
        if (bestMs == Double.MAX_VALUE) {
            log("No option at $HEAT_TEST_SIZE px found 7 or 8 boxes.")
        } else {
            log("Best at $HEAT_TEST_SIZE px: $bestProvider with $bestThreads threads, ${bestMs.toInt()} ms")
        }
        log("End: ${batteryTemperature()} C, thermal ${thermalStatus()}")
    }

    /** The test image has marker 7 with a 120-pixel code, 100 pixels right of centre. */
    private fun tagTest() {
        val image = assets.open("tag_test.png").use { BitmapFactory.decodeStream(it) }
        val reader = TagReader()
        val locator = TagLocator.forBackCamera(this)
        val tag = reader.read(image)
        if (tag == null) {
            log("TAG TEST: no tag found")
            return
        }
        val position = locator.locate(tag, image.width, image.height)
        log("TAG TEST: ${tag.plantId}, side ${tag.sidePixels} px, centre ${tag.centreX}, ${tag.centreY}")
        log("TAG TEST: ${describe(position)}, distance ${position.distanceMetres} m")
        val start = System.nanoTime()
        repeat(30) { reader.read(image) }
        log("TAG TEST: ${(System.nanoTime() - start) / 30_000_000.0} ms per read")
    }

    private fun heatTest() {
        val image = loadSample()
        val endAt = System.currentTimeMillis() + HEAT_TEST_MINUTES * 60_000L
        log("")
        log("HEAT TEST: $bestProvider, $bestThreads threads, $HEAT_TEST_SIZE px, $HEAT_TEST_MINUTES minutes")
        log("minutes, mean ms, fps, battery C, battery %, thermal status")

        createDetector(this, HEAT_TEST_SIZE, bestProvider, bestThreads).use { detector ->
            val startedAt = System.currentTimeMillis()
            while (!stopRequested && System.currentTimeMillis() < endAt) {
                val windowEnd = System.currentTimeMillis() + HEAT_LOG_SECONDS * 1000L
                var runs = 0
                var total = 0.0
                while (!stopRequested && System.currentTimeMillis() < windowEnd) {
                    val start = System.nanoTime()
                    detector.prepare(image)
                    detector.detect()
                    total += (System.nanoTime() - start) / 1e6
                    runs++
                }
                if (runs > 0) {
                    val mean = total / runs
                    val minutes = (System.currentTimeMillis() - startedAt) / 60_000.0
                    log(
                        "%5.1f, %6.1f, %5.1f, %4.1f, %d, %s"
                            .format(minutes, mean, 1000 / mean, batteryTemperature(), batteryPercent(), thermalStatus()),
                    )
                }
            }
        }
        log(if (stopRequested) "Heat test stopped early." else "Heat test finished.")
    }

    private fun batteryTemperature(): Double {
        val status = registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        return (status?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0) / 10.0
    }

    private fun batteryPercent(): Int =
        getSystemService(BatteryManager::class.java).getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)

    private fun thermalStatus(): String =
        when (getSystemService(PowerManager::class.java).currentThermalStatus) {
            PowerManager.THERMAL_STATUS_NONE -> "none"
            PowerManager.THERMAL_STATUS_LIGHT -> "light"
            PowerManager.THERMAL_STATUS_MODERATE -> "moderate"
            PowerManager.THERMAL_STATUS_SEVERE -> "severe"
            PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
            PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
            PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutdown"
            else -> "unknown"
        }

    private fun log(line: String) {
        Log.i("CRAP", line)
        runOnUiThread {
            results.append(line).append('\n')
            output.text = results
            scroll.post { scroll.fullScroll(ScrollView.FOCUS_DOWN) }
        }
    }

    private fun shareResults() {
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_TEXT, results.toString())
        }
        startActivity(Intent.createChooser(send, "Share results"))
    }
}
