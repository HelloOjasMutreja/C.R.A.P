package com.crap.speedtest

import android.content.Context
import android.graphics.Bitmap
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.core.Mat
import org.opencv.imgproc.Imgproc
import org.opencv.objdetect.ArucoDetector
import org.opencv.objdetect.DetectorParameters
import org.opencv.objdetect.Objdetect
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max

/** Printed width of the black square on a plant tag. Provisional: measure the real print. */
const val TAG_SIZE_METRES = 0.10

/** A plant tag seen in an image. Marker 7 is PLANT_007, matching live/markers.py. */
data class Tag(
    val markerId: Int,
    val corners: FloatArray,
    val sidePixels: Float,
    val centreX: Float,
    val centreY: Float,
) {
    val plantId: String get() = "PLANT_%03d".format(markerId)
}

/** Where a tag is relative to the camera. Positive bearing means the tag is to the right. */
data class TagPosition(val distanceMetres: Double, val bearingDegrees: Double)

/** Finds ArUco plant tags. Uses the same marker set as live/markers.py. */
class TagReader {

    private val detector: ArucoDetector

    init {
        check(OpenCVLoader.initLocal()) { "OpenCV did not load" }
        val parameters = DetectorParameters()
        // No bit correction: with only 16 bits per tag, correcting errors invents tags.
        parameters.set_errorCorrectionRate(0.0)
        detector = ArucoDetector(Objdetect.getPredefinedDictionary(Objdetect.DICT_4X4_50), parameters)
    }

    /** Return the largest tag, which is the closest plant, or null if none is visible. */
    fun read(image: Bitmap): Tag? = readAll(image).firstOrNull()

    /** Every tag in view, largest first. */
    fun readAll(image: Bitmap): List<Tag> {
        val colour = Mat()
        val grey = Mat()
        val ids = Mat()
        val found = ArrayList<Mat>()
        try {
            Utils.bitmapToMat(image, colour)
            Imgproc.cvtColor(colour, grey, Imgproc.COLOR_RGBA2GRAY)
            detector.detectMarkers(grey, found, ids)

            return found.indices.mapNotNull { i ->
                val points = FloatArray(8)
                found[i].get(0, 0, points)
                if (plausibleTag(sides(points))) tagFrom(ids.get(i, 0)[0].toInt(), points) else null
            }.sortedByDescending { it.sidePixels }
        } finally {
            colour.release()
            grey.release()
            ids.release()
            found.forEach { it.release() }
        }
    }

    private fun sides(p: FloatArray) = listOf(
        hypot(p[2] - p[0], p[3] - p[1]),
        hypot(p[4] - p[2], p[5] - p[3]),
        hypot(p[6] - p[4], p[7] - p[5]),
        hypot(p[0] - p[6], p[1] - p[7]),
    )

    private fun tagFrom(id: Int, p: FloatArray): Tag {
        return Tag(
            markerId = id,
            corners = p,
            sidePixels = sides(p).average().toFloat(),
            centreX = (p[0] + p[2] + p[4] + p[6]) / 4,
            centreY = (p[1] + p[3] + p[5] + p[7]) / 4,
        )
    }
}

/** Turns a tag's size and position in the image into distance and direction. */
class TagLocator(private val focalRatio: Double) {

    fun locate(tag: Tag, imageWidth: Int, imageHeight: Int): TagPosition {
        val focalPixels = focalRatio * max(imageWidth, imageHeight)
        val offset = tag.centreX - imageWidth / 2.0
        return TagPosition(
            distanceMetres = focalPixels * TAG_SIZE_METRES / tag.sidePixels,
            bearingDegrees = Math.toDegrees(atan2(offset, focalPixels)),
        )
    }

    companion object {
        /** Focal length divided by the sensor's long side, read from the main back camera. */
        fun forBackCamera(context: Context): TagLocator {
            val manager = context.getSystemService(CameraManager::class.java)
            for (id in manager.cameraIdList) {
                val info = manager.getCameraCharacteristics(id)
                if (info.get(CameraCharacteristics.LENS_FACING) != CameraCharacteristics.LENS_FACING_BACK) continue
                val focal = info.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull() ?: continue
                val sensor = info.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE) ?: continue
                return TagLocator(focal.toDouble() / max(sensor.width, sensor.height))
            }
            error("No back camera details found")
        }
    }
}

fun describe(position: TagPosition): String {
    val centimetres = (position.distanceMetres * 100).toInt()
    val degrees = abs(position.bearingDegrees).toInt()
    val side = if (position.bearingDegrees >= 0) "right" else "left"
    return if (degrees == 0) "$centimetres cm, straight ahead" else "$centimetres cm, $degrees° $side"
}
