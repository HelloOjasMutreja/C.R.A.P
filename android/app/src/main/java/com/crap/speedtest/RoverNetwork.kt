package com.crap.speedtest

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import java.io.IOException
import java.net.Inet4Address
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket

const val ROBOT_HOST = "192.168.4.1"
const val ROBOT_PORT = 3333
private const val CONNECT_TIMEOUT_MS = 3000

/**
 * Finds the rover's Wi-Fi. It has no internet, so Android would otherwise send our traffic
 * over mobile data; this asks for Wi-Fi directly and ties the socket to it.
 */
class RoverNetwork(context: Context) : AutoCloseable {

    @Volatile
    private var wifi: Network? = null

    private val manager = context.getSystemService(ConnectivityManager::class.java)
    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            wifi = network
        }

        override fun onLost(network: Network) {
            if (wifi == network) wifi = null
        }
    }

    init {
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        manager.requestNetwork(request, callback)
    }

    fun connect(host: String = ROBOT_HOST, port: Int = ROBOT_PORT): Socket {
        val network = wifi ?: throw IOException("Not on Wi-Fi")
        val socket = Socket()
        network.bindSocket(socket)
        socket.connect(InetSocketAddress(host, port), CONNECT_TIMEOUT_MS)
        return socket
    }

    /** The phone's address on the rover's Wi-Fi, for the remote page. */
    fun address(): InetAddress? {
        val network = wifi ?: return null
        return manager.getLinkProperties(network)?.linkAddresses?.map { it.address }?.firstOrNull { it is Inet4Address }
    }

    override fun close() {
        manager.unregisterNetworkCallback(callback)
    }
}
