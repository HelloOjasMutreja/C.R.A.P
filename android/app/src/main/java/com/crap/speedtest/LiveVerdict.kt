package com.crap.speedtest

const val VERDICT_WINDOW = 8
const val VERDICT_MIN_HITS = 3

/** Smooths the live result: a condition must appear in 3 of the last 8 frames to be shown. */
class LiveVerdict {

    private val recent = ArrayDeque<List<Box>>()

    fun add(boxes: List<Box>): String {
        recent.addLast(boxes)
        if (recent.size > VERDICT_WINDOW) recent.removeFirst()

        val sick = HashMap<Int, Int>()
        var healthyFrames = 0
        var healthyClass = -1

        for (frame in recent) {
            val classes = frame.map { it.classId }.toSet()
            for (id in classes) {
                if (!LABELS[id].healthy) sick[id] = (sick[id] ?: 0) + 1
            }
            val healthy = classes.firstOrNull { LABELS[it].healthy }
            if (healthy != null) {
                healthyFrames++
                healthyClass = healthy
            }
        }

        val strongest = sick.entries.filter { it.value >= VERDICT_MIN_HITS }.maxByOrNull { it.value }
        return when {
            strongest != null -> {
                val label = LABELS[strongest.key]
                "Possible ${label.condition} on ${label.species}"
            }
            healthyFrames >= VERDICT_MIN_HITS -> "${LABELS[healthyClass].species} looks healthy"
            else -> "Point the camera at a leaf"
        }
    }
}
