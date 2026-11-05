package com.crap.speedtest

import kotlin.math.abs

/** A plant tag seen from the rover. Positive bearing means the tag is to the right. */
data class Sighting(val plantId: String, val distanceCm: Double, val bearingDegrees: Double)

interface Mover {
    fun moveCentimetres(distance: Double)
    fun turnDegrees(angle: Double)
}

interface Eyes {
    /** Tags in a frame taken after this call, closest first. Blocks until there is one. */
    fun look(): List<Sighting>
}

data class VisitOutcome(val status: String, val actionId: String?, val actionType: String?)

interface Inspector {
    /** Record a visit from where the rover is now and return what the rules decided. */
    fun visit(plantId: String): VisitOutcome

    /** Close an action the mission carried out in its own way. */
    fun markDone(plantId: String, actionId: String, note: String)
}

data class MissionSettings(
    val standoffCm: Double = 40.0,
    val toleranceCm: Double = 6.0,
    // One encoder pulse is about 4.7 degrees of turn, so finer aiming is not possible.
    val faceWithinDegrees: Double = 6.0,
    val maxStepCm: Double = 40.0,
    val maxApproachSteps: Int = 12,
    val scanStepDegrees: Double = 30.0,
    val maxViews: Int = 3,
    val closerCm: Double = 8.0,
    val retreatCm: Double = 25.0,
    val maxTravelCm: Double = 600.0,
    /** Gap between plants along a straight row, with the next plant to the right. Negative means left. Null turns the row step off. */
    val rowSpacingCm: Double? = null,
)

data class MissionResult(val visited: List<String>, val missed: List<String>, val ending: String)

private const val LAST_MARKER = 49 // The tags use the 50-marker ArUco set, numbered from 0.

/** Reads a list like "1-5, 7" into plant IDs. Returns null if it is empty or not understood. */
fun parsePlantList(text: String): Set<String>? {
    val plants = LinkedHashSet<String>()
    for (part in text.split(",").map { it.trim() }.filter { it.isNotEmpty() }) {
        val ends = part.split("-").map { it.trim().toIntOrNull() ?: return null }
        val first = ends.first()
        val last = ends.last()
        if (ends.size > 2 || first < 0 || last > LAST_MARKER || first > last) return null
        (first..last).mapTo(plants) { "PLANT_%03d".format(it) }
    }
    return plants.ifEmpty { null }
}

data class MissionPlan(val plants: Set<String>, val rowSpacingCm: Double?) {
    /** A row needs more driving per plant than a single stop, so its travel limit grows with the row. */
    fun settings(): MissionSettings {
        val base = MissionSettings(rowSpacingCm = rowSpacingCm)
        val spacing = rowSpacingCm ?: return base
        return base.copy(maxTravelCm = maxOf(base.maxTravelCm, plants.size * (abs(spacing) + ROW_DRIVING_PER_PLANT_CM)))
    }
}

private const val MIN_ROW_SPACING_CM = 20.0
private const val MAX_ROW_SPACING_CM = 200.0
private const val ROW_DRIVING_PER_PLANT_CM = 80.0 // Back away, return to the standoff, and closer views.

/** Reads "1-6" or, for a straight row, "1-6 / 60": the plants, then their spacing in cm. Null if not understood. */
fun parseMissionPlan(text: String): MissionPlan? {
    val parts = text.split("/")
    if (parts.size > 2) return null
    val plants = parsePlantList(parts[0]) ?: return null
    if (parts.size == 1) return MissionPlan(plants, null)
    val spacing = parts[1].trim().toDoubleOrNull() ?: return null
    if (abs(spacing) !in MIN_ROW_SPACING_CM..MAX_ROW_SPACING_CM) return null
    return MissionPlan(plants, spacing)
}

private class TravelLimitReached : Exception()

/**
 * Visits every plant tag it can find: find, approach, inspect, back away, repeat.
 *
 * The mission owns all movement near plants. It never runs the rules' "move on" plan, which
 * drives forward blindly and would hit the plant in front of it, and it never sprays: spraying
 * stays with a person. The rover has no obstacle sensors, so a person must supervise with STOP.
 */
class Mission(
    private val mover: Mover,
    private val eyes: Eyes,
    private val inspector: Inspector,
    private val settings: MissionSettings = MissionSettings(),
    private val report: (String) -> Unit = {},
    private val stopRequested: () -> Boolean = { false },
    /** The only plants to approach, so a misread tag with another number is ignored. Null allows any. */
    private val expected: Set<String>? = null,
) {
    private var travelled = 0.0
    private val visited = ArrayList<String>()
    private val missed = ArrayList<String>()

    fun run(): MissionResult {
        val ending = try {
            while (true) {
                checkStop()
                val target = findNextPlant() ?: break
                report("Approaching ${target.plantId}")
                if (approach(target.plantId)) {
                    inspect(target.plantId)
                    visited.add(target.plantId)
                } else {
                    report("Could not reach ${target.plantId}")
                    missed.add(target.plantId)
                }
                move(-settings.retreatCm)
                stepAlongRow()
            }
            "finished"
        } catch (_: TravelLimitReached) {
            "travel limit reached"
        } catch (error: RobotError) {
            "stopped: ${error.message}"
        }
        report("Mission $ending: ${visited.size} plants visited")
        return MissionResult(visited, missed, ending)
    }

    /**
     * Slide sideways to face the next stake square on. Searching on the spot can fail in a row,
     * because a tag seen from too sharp an angle cannot be read.
     */
    private fun stepAlongRow() {
        val spacing = settings.rowSpacingCm ?: return
        val left = expected?.filter { it !in visited && it !in missed } ?: return
        if (left.isEmpty()) return
        report("Moving along the row to the next plant")
        val side = if (spacing > 0) 90.0 else -90.0
        turn(side)
        move(abs(spacing))
        turn(-side)
    }

    /** Turn on the spot until a plant not yet handled is in view. */
    private fun findNextPlant(): Sighting? {
        val steps = (360 / settings.scanStepDegrees).toInt()
        repeat(steps) {
            checkStop()
            val found = eyes.look().firstOrNull {
                it.plantId !in visited && it.plantId !in missed && (expected == null || it.plantId in expected)
            }
            if (found != null) return found
            report("Searching for a plant tag")
            turn(settings.scanStepDegrees)
        }
        return null
    }

    /** Face the tag, then close the gap in small steps, looking again after every move. */
    private fun approach(plantId: String): Boolean {
        var lastStepTaken = false
        repeat(settings.maxApproachSteps) {
            checkStop()
            val tag = see(plantId)
            if (tag == null) {
                // A low or high tag leaves the picture up close, just as the rover gets there.
                if (lastStepTaken) report("$plantId's tag left the picture close up. Treating this as arrived.")
                return lastStepTaken
            }
            val gap = tag.distanceCm - settings.standoffCm
            when {
                abs(tag.bearingDegrees) > settings.faceWithinDegrees -> turn(tag.bearingDegrees)
                abs(gap) <= settings.toleranceCm -> return true
                else -> {
                    val step = gap.coerceIn(-settings.maxStepCm, settings.maxStepCm)
                    move(step)
                    lastStepTaken = step == gap
                }
            }
        }
        return false
    }

    /** Two tries, because one frame can miss a tag. */
    private fun see(plantId: String): Sighting? {
        repeat(2) {
            eyes.look().firstOrNull { it.plantId == plantId }?.let { return it }
        }
        return null
    }

    private fun inspect(plantId: String) {
        for (view in 1..settings.maxViews) {
            checkStop()
            val outcome = inspector.visit(plantId)
            report("$plantId: ${outcome.status}, next ${outcome.actionType ?: "nothing"}")

            when (outcome.actionType) {
                "inspect_closer" -> {
                    // The arm is not available yet, so get a new view by driving a little closer.
                    if (view == settings.maxViews) return
                    move(settings.closerCm)
                    inspector.markDone(plantId, outcome.actionId!!, "Moved ${settings.closerCm.toInt()} cm closer.")
                }
                "reposition_and_retry" -> {
                    if (view == settings.maxViews) return
                    move(-settings.closerCm)
                    inspector.markDone(plantId, outcome.actionId!!, "Moved ${settings.closerCm.toInt()} cm back.")
                }
                "move_on" -> {
                    inspector.markDone(plantId, outcome.actionId!!, "Mission moved on.")
                    return
                }
                // Spraying and reviews stay open for a person.
                else -> return
            }
        }
    }

    private fun move(distance: Double) {
        checkStop()
        travelled += abs(distance)
        if (travelled > settings.maxTravelCm) throw TravelLimitReached()
        mover.moveCentimetres(distance)
    }

    private fun turn(angle: Double) {
        checkStop()
        mover.turnDegrees(angle)
    }

    private fun checkStop() {
        if (stopRequested()) throw RobotError("Stopped by the operator")
    }
}
