package com.crap.speedtest

import java.io.BufferedReader
import java.io.IOException
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import java.security.MessageDigest
import java.util.concurrent.Executors
import kotlin.concurrent.thread

const val REMOTE_PORT = 8080
private const val READ_TIMEOUT_MS = 3000
private const val MAX_LINE = 2000
private const val MAX_HEADERS = 40
private const val WORKERS = 4
private const val WRONG_PINS_ALLOWED = 5
private const val LOCKOUT_MS = 60_000L
private const val WATCHED_MS = 3000L
private val ACTIONS = setOf("run", "approve", "skip")

/** What the remote page can see and do. Calls arrive on server threads. */
interface RemoteControls {
    fun page(): ByteArray
    fun status(): String
    fun frame(): ByteArray?
    fun stop()
    fun startMission(plants: String)
    fun act(action: String)
}

private class Reply(val status: Int, val type: String, val body: ByteArray) {
    constructor(status: Int, words: String) : this(status, "text/plain; charset=utf-8", words.toByteArray())
}

/**
 * The phone's screen rides on the rover, so a second device on the rover's Wi-Fi uses this page.
 * STOP needs no PIN: anyone who can reach it should be able to stop the rover. Anything that
 * makes the rover act needs the PIN shown on the phone. Only [allowed] local addresses are
 * served, which keeps this off the phone's mobile data connection.
 */
class RemoteServer(
    private val pin: String,
    private val controls: RemoteControls,
    port: Int = REMOTE_PORT,
    private val allowed: (InetAddress) -> Boolean = { true },
    private val clock: () -> Long = System::currentTimeMillis,
) : AutoCloseable {
    private val server = ServerSocket(port)
    private val workers = Executors.newFixedThreadPool(WORKERS)
    private var wrongPins = 0
    private var lockedUntil = 0L

    @Volatile
    private var lastStatusAt = 0L

    @Volatile
    private var lastFrameAt = 0L

    val port: Int get() = server.localPort

    /** How long since the page last checked in. It does this twice a second while open. */
    val quietMs: Long get() = clock() - lastStatusAt

    /** Pictures cost time on the analysis thread, so make them only while someone is looking. */
    val watched: Boolean get() = clock() - lastFrameAt < WATCHED_MS

    init {
        thread(isDaemon = true, name = "remote-server") {
            while (!server.isClosed) {
                try {
                    val link = server.accept()
                    workers.execute { serve(link) }
                } catch (_: IOException) {
                    // Closed, or one bad connection. The loop's check decides which.
                }
            }
        }
    }

    private fun serve(link: Socket) {
        link.use {
            try {
                if (!allowed(link.localAddress)) return
                link.soTimeout = READ_TIMEOUT_MS
                val input = BufferedReader(InputStreamReader(link.getInputStream(), Charsets.ISO_8859_1))
                val first = readLine(input) ?: return
                val parts = first.split(" ")
                if (parts.size != 3) return
                val headers = HashMap<String, String>()
                repeat(MAX_HEADERS) {
                    val line = readLine(input) ?: return
                    if (line.isEmpty()) {
                        write(link, respond(parts[0], parts[1], headers))
                        return
                    }
                    val colon = line.indexOf(':')
                    if (colon > 0) headers[line.take(colon).trim().lowercase()] = line.drop(colon + 1).trim()
                }
            } catch (_: IOException) {
                // The other device went away. Nothing to tell it.
            }
        }
    }

    private fun readLine(input: BufferedReader): String? = input.readLine()?.takeIf { it.length <= MAX_LINE }

    private fun respond(method: String, target: String, headers: Map<String, String>): Reply {
        val path = target.substringBefore('?')
        val query = queryOf(target.substringAfter('?', ""))
        return when (method) {
            "GET" -> read(path)
            "POST" -> command(path, query, headers)
            else -> Reply(405, "Not allowed")
        }
    }

    private fun read(path: String): Reply = when (path) {
        "/" -> Reply(200, "text/html; charset=utf-8", controls.page())
        "/status" -> {
            lastStatusAt = clock()
            Reply(200, "application/json", controls.status().toByteArray())
        }
        "/frame.jpg" -> {
            lastFrameAt = clock()
            controls.frame()?.let { Reply(200, "image/jpeg", it) } ?: Reply(204, "")
        }
        else -> Reply(404, "Not found")
    }

    private fun command(path: String, query: Map<String, String>, headers: Map<String, String>): Reply {
        if (path == "/stop") {
            controls.stop()
            return Reply(200, "Stopping")
        }
        if (path != "/mission" && path != "/action") return Reply(404, "Not found")
        pinProblem(headers["x-pin"].orEmpty())?.let { return it }
        if (path == "/mission") {
            controls.startMission(query["plants"].orEmpty())
            return Reply(200, "Starting")
        }
        val action = query["do"].orEmpty()
        if (action !in ACTIONS) return Reply(400, "Unknown action")
        controls.act(action)
        return Reply(200, "Done")
    }

    /** A few wrong tries lock everyone out for a minute, so the PIN cannot be guessed quickly. */
    @Synchronized
    private fun pinProblem(tried: String): Reply? {
        if (clock() < lockedUntil) return Reply(429, "Too many wrong PINs. Wait a minute.")
        if (MessageDigest.isEqual(tried.toByteArray(), pin.toByteArray())) {
            wrongPins = 0
            return null
        }
        if (++wrongPins >= WRONG_PINS_ALLOWED) {
            wrongPins = 0
            lockedUntil = clock() + LOCKOUT_MS
        }
        return Reply(403, "Wrong PIN")
    }

    private fun queryOf(text: String): Map<String, String> =
        text.split("&").filter { "=" in it }.associate { pair ->
            val (name, value) = pair.split("=", limit = 2)
            name to URLDecoder.decode(value, "UTF-8")
        }

    private fun write(link: Socket, reply: Reply) {
        val head = "HTTP/1.1 ${reply.status} ${if (reply.status < 300) "OK" else "Error"}\r\n" +
            "Content-Type: ${reply.type}\r\n" +
            "Content-Length: ${reply.body.size}\r\n" +
            "Cache-Control: no-store\r\n" +
            "Connection: close\r\n\r\n"
        link.getOutputStream().apply {
            write(head.toByteArray())
            write(reply.body)
            flush()
        }
    }

    override fun close() {
        server.close()
        workers.shutdown()
    }
}
