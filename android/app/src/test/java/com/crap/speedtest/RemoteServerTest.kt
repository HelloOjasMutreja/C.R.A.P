package com.crap.speedtest

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.HttpURLConnection
import java.net.URL

private class FakeControls : RemoteControls {
    val log = ArrayList<String>()
    var picture: ByteArray? = null

    override fun page() = "<h1>Rover</h1>".toByteArray()
    override fun status() = """{"robot":true}"""
    override fun frame() = picture
    override fun stop() {
        log.add("stop")
    }

    override fun startMission(plants: String) {
        log.add("mission $plants")
    }

    override fun act(action: String) {
        log.add("act $action")
    }
}

class RemoteServerTest {
    private val controls = FakeControls()
    private var now = 1_000_000L
    private val server = RemoteServer("123456", controls, port = 0, clock = { now })

    @After
    fun close() = server.close()

    private fun call(method: String, path: String, pin: String? = null): Pair<Int, String> {
        val link = URL("http://127.0.0.1:${server.port}$path").openConnection() as HttpURLConnection
        link.requestMethod = method
        if (pin != null) link.setRequestProperty("X-Pin", pin)
        val code = link.responseCode
        val stream = if (code < 400) link.inputStream else link.errorStream
        return code to (stream?.readBytes()?.decodeToString() ?: "")
    }

    @Test
    fun servesThePageAndStatus() {
        assertEquals(200 to "<h1>Rover</h1>", call("GET", "/"))
        assertEquals(200 to """{"robot":true}""", call("GET", "/status"))
        assertEquals(404, call("GET", "/nothing").first)
    }

    @Test
    fun stopNeedsNoPinButMustBeAPost() {
        assertEquals(404, call("GET", "/stop").first)
        assertTrue(controls.log.isEmpty())

        assertEquals(200, call("POST", "/stop").first)
        assertEquals(listOf("stop"), controls.log)
    }

    @Test
    fun actingNeedsThePin() {
        assertEquals(403, call("POST", "/mission?plants=1-3").first)
        assertEquals(403, call("POST", "/action?do=approve", "000000").first)
        assertTrue(controls.log.isEmpty())

        assertEquals(200, call("POST", "/mission?plants=1-3%2C%207", "123456").first)
        assertEquals(200, call("POST", "/action?do=approve", "123456").first)
        assertEquals(listOf("mission 1-3, 7", "act approve"), controls.log)
    }

    @Test
    fun unknownActionsAreRefused() {
        assertEquals(400, call("POST", "/action?do=spray", "123456").first)
        assertTrue(controls.log.isEmpty())
    }

    @Test
    fun wrongPinsLockEveryoneOutForAMinute() {
        repeat(5) { assertEquals(403, call("POST", "/mission", "000000").first) }

        assertEquals(429, call("POST", "/mission", "123456").first)
        assertEquals(200, call("POST", "/stop").first)

        now += 60_000
        assertEquals(200, call("POST", "/mission", "123456").first)
    }

    @Test
    fun aMissingPictureIsNotAnError() {
        assertEquals(204, call("GET", "/frame.jpg").first)
        controls.picture = byteArrayOf(1, 2, 3)
        assertEquals(200, call("GET", "/frame.jpg").first)
    }

    @Test
    fun knowsWhenThePageWentQuiet() {
        call("GET", "/status")
        assertEquals(0, server.quietMs)

        now += 5000
        assertEquals(5000, server.quietMs)
    }

    @Test
    fun picturesAreOnlyMadeWhileWatched() {
        assertFalse(server.watched)
        call("GET", "/frame.jpg")
        assertTrue(server.watched)

        now += 3000
        assertFalse(server.watched)
    }

    @Test
    fun eachAnswerFreesItsWorkerAtOnce() {
        val start = System.currentTimeMillis()
        repeat(20) { call("GET", "/status") }

        assertTrue(System.currentTimeMillis() - start < 2000)
    }

    @Test
    fun connectionsOnOtherNetworksAreDropped() {
        val closed = RemoteServer("123456", controls, port = 0, allowed = { false })
        val link = URL("http://127.0.0.1:${closed.port}/").openConnection() as HttpURLConnection
        val refused = runCatching { link.responseCode }.isFailure
        closed.close()

        assertTrue(refused)
    }
}
