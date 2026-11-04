package com.crap.speedtest

import org.json.JSONException
import org.json.JSONObject
import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.Socket
import java.util.concurrent.ExecutionException
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import kotlin.concurrent.thread

private const val PING_EVERY_MS = 300L
private const val READ_TIMEOUT_MS = 3000
private const val RETRY_MS = 2000L
private const val SEND_TIMEOUT_MS = 2000L
private const val MOVE_TIMEOUT_MS = 30_000L
private const val SENSOR_MAX_AGE_MS = 10_000L
private const val MOVE_SPEED = 120
private const val TURN_SPEED = 110

// The action plans use timed drives; the firmware moves by distance. Provisional until measured.
private const val CM_PER_SECOND = 30.0
private const val DEGREES_PER_SECOND = 45.0

// Statuses that end a move badly. COMPLETE is the only good ending.
private val FAILED_ENDINGS = setOf(
    "STOPPED", "TIMEOUT", "STALLED", "SILENCE_STOP", "INVALID_DISTANCE",
    "INVALID_ANGLE", "INVALID_JSON", "UNKNOWN_COMMAND", "COMMAND_TOO_LONG",
)

/**
 * Talks to the ESP32 over Wi-Fi with one JSON message per line, and keeps the link alive.
 * Moves block until the ESP32 reports how they ended, so run them off the main thread.
 */
class WifiRobot(private val connect: () -> Socket) : Robot, AutoCloseable {

    override val hasArm = false

    @Volatile
    var connected = false
        private set

    @Volatile
    private var closed = false

    @Volatile
    private var halted = false

    @Volatile
    private var output: OutputStream? = null

    @Volatile
    private var socket: Socket? = null

    @Volatile
    private var humidity: Double? = null

    @Volatile
    private var temperature: Double? = null

    @Volatile
    private var sensorsAt = 0L

    private val writer = Executors.newSingleThreadExecutor()
    private val statuses = LinkedBlockingQueue<String>()

    init {
        thread(isDaemon = true, name = "robot-link") { keepConnected() }
        thread(isDaemon = true, name = "robot-ping") { keepPinging() }
    }

    private fun keepConnected() {
        while (!closed) {
            try {
                connect().use { link ->
                    link.soTimeout = READ_TIMEOUT_MS
                    link.tcpNoDelay = true
                    socket = link
                    output = link.getOutputStream()
                    connected = true
                    val input = BufferedReader(InputStreamReader(link.getInputStream()))
                    while (!closed) {
                        val line = input.readLine() ?: break
                        handle(line)
                    }
                }
            } catch (_: IOException) {
                // Out of range or switched off. Keep trying.
            }
            connected = false
            output = null
            socket = null
            statuses.offer(LINK_LOST)
            if (!closed) Thread.sleep(RETRY_MS)
        }
    }

    private fun keepPinging() {
        while (!closed) {
            Thread.sleep(PING_EVERY_MS)
            if (connected) {
                try {
                    send("""{"cmd":"PING"}""")
                } catch (_: RobotError) {
                    // The link thread notices a lost connection and reconnects.
                }
            }
        }
    }

    private fun handle(line: String) {
        val message = try {
            JSONObject(line)
        } catch (_: JSONException) {
            return
        }
        when (message.optString("type")) {
            "STATUS" -> statuses.offer(message.optString("status"))
            "TELEMETRY" -> {
                humidity = if (message.isNull("humidity")) null else message.getDouble("humidity")
                temperature = if (message.isNull("temperature")) null else message.getDouble("temperature")
                sensorsAt = System.currentTimeMillis()
            }
        }
    }

    private fun send(json: String) {
        val job = writer.submit {
            val stream = output ?: throw IOException("not connected")
            stream.write("$json\n".toByteArray())
            stream.flush()
        }
        try {
            job.get(SEND_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        } catch (error: ExecutionException) {
            socket?.close()
            throw RobotError("Lost the robot: ${error.cause?.message}")
        } catch (error: TimeoutException) {
            socket?.close()
            throw RobotError("Lost the robot: sending timed out")
        }
    }

    /** Send a move and wait for the ESP32 to say how it ended. */
    private fun runMove(json: String, label: String) {
        if (halted) throw RobotError("Stopped by the operator")
        if (!connected) throw RobotError("Robot is not connected")
        statuses.clear()
        send(json)

        val deadline = System.currentTimeMillis() + MOVE_TIMEOUT_MS
        while (true) {
            val left = deadline - System.currentTimeMillis()
            val status = statuses.poll(left, TimeUnit.MILLISECONDS)
            when {
                status == null -> {
                    stop()
                    throw RobotError("$label got no reply from the robot")
                }
                status == "COMPLETE" || status == "TOO_SMALL" -> return
                status == LINK_LOST -> throw RobotError("Lost the robot during $label")
                status in FAILED_ENDINGS -> throw RobotError("$label ended with $status")
            }
        }
    }

    /** Positive is forward. */
    fun moveCentimetres(distance: Double, speed: Int = MOVE_SPEED) {
        val json = JSONObject().put("cmd", "MOVE_CM").put("distance", distance).put("speed", speed)
        runMove(json.toString(), "move")
    }

    /** Positive is clockwise, to the right. */
    fun turnDegrees(angle: Double, speed: Int = TURN_SPEED) {
        val json = JSONObject().put("cmd", "TURN_DEG").put("angle", angle).put("speed", speed)
        runMove(json.toString(), "turn")
    }

    override fun drive(command: String, ms: Int) {
        val seconds = ms / 1000.0
        when (command) {
            "forward" -> moveCentimetres(seconds * CM_PER_SECOND)
            "back" -> moveCentimetres(-seconds * CM_PER_SECOND)
            "right" -> turnDegrees(seconds * DEGREES_PER_SECOND)
            "left" -> turnDegrees(-seconds * DEGREES_PER_SECOND)
            "stop" -> stop()
            else -> throw RobotError("Unknown drive command: $command")
        }
    }

    override fun arm(pose: String) {
        throw RobotError("Arm commands are not in the ESP32 firmware yet")
    }

    override fun spray(ms: Int) {
        throw RobotError("Spray commands are not in the ESP32 firmware yet")
    }

    /** Stops now and refuses further moves until [allowMoves], so a queued move cannot follow a stop. */
    override fun stop() {
        halted = true
        send("""{"cmd":"STOP"}""")
    }

    /** Call when a person asks for a move, before it is queued. */
    fun allowMoves() {
        halted = false
    }

    /** The latest DHT22 reading, or nothing if the sensor failed or the reading is old. */
    fun sensors(): Map<String, Double?> {
        val rh = humidity
        val celsius = temperature
        val fresh = System.currentTimeMillis() - sensorsAt <= SENSOR_MAX_AGE_MS
        if (!fresh || rh == null || celsius == null) return emptyMap()
        return mapOf("temperature_c" to celsius, "humidity_rh" to rh)
    }

    override fun close() {
        closed = true
        socket?.close()
        writer.shutdown()
    }

    private companion object {
        const val LINK_LOST = "LINK_LOST"
    }
}
