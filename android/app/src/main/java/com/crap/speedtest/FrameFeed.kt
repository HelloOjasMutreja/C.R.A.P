package com.crap.speedtest

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import java.io.DataInputStream
import java.io.IOException
import java.net.Socket
import kotlin.concurrent.thread

const val FRAME_PORT = 3334
private const val RETRY_MS = 1000L
private const val MAX_FRAME_BYTES = 4_000_000

/** Reads camera frames from firmware/simulate_field.py, in place of the real camera. */
class FrameFeed(private val host: String, private val onFrame: (Bitmap) -> Unit) : AutoCloseable {

    @Volatile
    private var closed = false

    @Volatile
    private var socket: Socket? = null

    init {
        thread(isDaemon = true, name = "frame-feed") { keepReading() }
    }

    private fun keepReading() {
        while (!closed) {
            try {
                Socket(host, FRAME_PORT).use { link ->
                    socket = link
                    val input = DataInputStream(link.getInputStream().buffered())
                    while (!closed) {
                        val size = input.readInt()
                        if (size !in 1..MAX_FRAME_BYTES) throw IOException("Bad frame size: $size")
                        val data = ByteArray(size)
                        input.readFully(data)
                        BitmapFactory.decodeByteArray(data, 0, size)?.let(onFrame)
                    }
                }
            } catch (error: IOException) {
                Log.i("CRAP", "Frame feed: ${error.message}")
            }
            if (!closed) Thread.sleep(RETRY_MS)
        }
    }

    override fun close() {
        closed = true
        socket?.close()
    }
}
