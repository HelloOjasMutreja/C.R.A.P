package com.crap.speedtest

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.PrintWriter
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread

/** A stand-in ESP32 on a local socket. [reply] decides how it answers each command. */
private class FakeEsp32(val reply: (JSONObject, PrintWriter) -> Unit) : AutoCloseable {
    val server = ServerSocket(0, 5, InetAddress.getLoopbackAddress())
    val commands = CopyOnWriteArrayList<String>()
    var client: Socket? = null

    init {
        thread(isDaemon = true) {
            try {
                while (true) {
                    val link = server.accept()
                    client = link
                    thread(isDaemon = true) { serve(link) }
                }
            } catch (_: Exception) {
                // Closed at the end of the test.
            }
        }
    }

    private fun serve(link: Socket) {
        try {
            val out = PrintWriter(link.getOutputStream(), true)
            out.println("""{"type":"STATUS","status":"CONNECTED"}""")
            val input = BufferedReader(InputStreamReader(link.getInputStream()))
            while (true) {
                val line = input.readLine() ?: break
                val message = JSONObject(line)
                commands.add(message.getString("cmd"))
                reply(message, out)
            }
        } catch (_: Exception) {
            // The client went away.
        }
    }

    override fun close() {
        client?.close()
        server.close()
    }
}

private fun status(out: PrintWriter, words: String) = out.println("""{"type":"STATUS","status":"$words"}""")

class WifiRobotTest {

    private var esp: FakeEsp32? = null
    private var robot: WifiRobot? = null

    private fun start(reply: (JSONObject, PrintWriter) -> Unit): WifiRobot {
        val fake = FakeEsp32(reply).also { esp = it }
        val made = WifiRobot { Socket(InetAddress.getLoopbackAddress(), fake.server.localPort) }
        robot = made
        waitFor { made.connected }
        return made
    }

    private fun waitFor(condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 3000
        while (!condition()) {
            assertTrue("timed out", System.currentTimeMillis() < deadline)
            Thread.sleep(10)
        }
    }

    @After
    fun tearDown() {
        robot?.close()
        esp?.close()
    }

    @Before
    fun clear() {
        esp = null
        robot = null
    }

    private val finishesMoves: (JSONObject, PrintWriter) -> Unit = { message, out ->
        when (message.getString("cmd")) {
            "MOVE_CM" -> {
                status(out, "MOVEMENT_STARTED")
                status(out, "COMPLETE")
            }
            "TURN_DEG" -> {
                status(out, "TURN_STARTED")
                status(out, "COMPLETE")
            }
        }
    }

    @Test
    fun moveWaitsForComplete() {
        val robot = start(finishesMoves)

        robot.moveCentimetres(50.0)
        robot.turnDegrees(-30.0)

        assertTrue("MOVE_CM" in esp!!.commands)
        assertTrue("TURN_DEG" in esp!!.commands)
    }

    @Test
    fun timedDriveBecomesADistance() {
        var distance = 0.0
        val robot = start { message, out ->
            if (message.getString("cmd") == "MOVE_CM") {
                distance = message.getDouble("distance")
                status(out, "COMPLETE")
            }
        }

        robot.drive("back", 300)

        assertEquals(-9.0, distance, 0.001)
    }

    @Test
    fun badEndingsRaiseAnError() {
        for (ending in listOf("STALLED", "TIMEOUT", "STOPPED", "SILENCE_STOP", "UNKNOWN_COMMAND")) {
            val robot = start { message, out ->
                if (message.getString("cmd") == "MOVE_CM") status(out, ending)
            }

            val error = assertThrows(RobotError::class.java) { robot.moveCentimetres(10.0) }

            assertTrue(error.message!!, ending in error.message!!)
            tearDown()
        }
    }

    @Test
    fun aMoveTooSmallToMeasureIsNotAFailure() {
        val robot = start { message, out ->
            if (message.getString("cmd") == "TURN_DEG") status(out, "TOO_SMALL")
        }

        robot.turnDegrees(1.0)
    }

    @Test
    fun heartbeatIsSentWithoutBeingAsked() {
        start { _, _ -> }

        waitFor { esp!!.commands.count { it == "PING" } >= 3 }
    }

    @Test
    fun readsSensorsAndIgnoresFailedOnes() {
        val robot = start { message, out ->
            if (message.getString("cmd") == "PING") {
                out.println("""{"type":"TELEMETRY","humidity":72.5,"temperature":29.1,"left_ticks":3}""")
            }
        }

        waitFor { robot.sensors().isNotEmpty() }
        assertEquals(72.5, robot.sensors()["humidity_rh"]!!, 0.0)
        assertEquals(29.1, robot.sensors()["temperature_c"]!!, 0.0)
    }

    @Test
    fun nullSensorReadingGivesNothing() {
        val robot = start { message, out ->
            if (message.getString("cmd") == "PING") {
                out.println("""{"type":"TELEMETRY","humidity":null,"temperature":null}""")
            }
        }

        Thread.sleep(500)

        assertEquals(emptyMap<String, Double?>(), robot.sensors())
    }

    @Test
    fun losingTheLinkDuringAMoveFailsIt() {
        val robot = start { message, _ ->
            if (message.getString("cmd") == "MOVE_CM") esp!!.client!!.close()
        }

        val error = assertThrows(RobotError::class.java) { robot.moveCentimetres(20.0) }

        assertTrue(error.message!!, "Lost" in error.message!!)
    }

    @Test
    fun notConnectedFailsStraightAway() {
        val made = WifiRobot { throw java.io.IOException("no rover") }
        robot = made

        assertFalse(made.connected)
        assertThrows(RobotError::class.java) { made.moveCentimetres(10.0) }
    }

    @Test
    fun armStepsFailBecauseTheFirmwareHasNoArm() {
        val robot = start { _, _ -> }

        assertFalse(robot.hasArm)
        assertThrows(RobotError::class.java) { robot.arm("inspect") }
        assertThrows(RobotError::class.java) { robot.spray(500) }
    }

    @Test
    fun aMoveQueuedBeforeStopIsRefusedAfterIt() {
        val robot = start(finishesMoves)
        robot.allowMoves()

        robot.stop()
        val error = assertThrows(RobotError::class.java) { robot.moveCentimetres(30.0) }

        assertTrue(error.message!!, "Stopped" in error.message!!)
        assertFalse("MOVE_CM" in esp!!.commands)

        robot.allowMoves()
        robot.moveCentimetres(30.0)
        assertTrue("MOVE_CM" in esp!!.commands)
    }

    @Test
    fun reconnectsAfterADrop() {
        val robot = start(finishesMoves)

        esp!!.client!!.close()
        waitFor { !robot.connected }
        waitFor { robot.connected }

        robot.moveCentimetres(10.0)
    }
}
