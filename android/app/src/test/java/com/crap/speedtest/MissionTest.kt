package com.crap.speedtest

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Random
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.round
import kotlin.math.sin

private const val FIELD_OF_VIEW = 35.0
private const val TAG_RANGE_CM = 250.0
private const val TICK_CM = 1.02
private const val TICK_DEGREES = 4.7

/** A flat field with a rover and tagged plants, with the firmware's coarse encoder steps. */
private class Field(
    val plants: Map<String, Pair<Double, Double>>,
    seed: Long = 1,
    val slip: Double = 0.0,
    val noise: Double = 0.0,
) : Mover, Eyes {
    private val random = Random(seed)
    var x = 0.0
    var y = 0.0
    var heading = 0.0 // Degrees clockwise from straight ahead, which is +y.
    var moves = 0
    var failAfter = Int.MAX_VALUE
    val log = ArrayList<String>()

    private fun wobble(size: Double) = 1 + (random.nextDouble() * 2 - 1) * size

    override fun moveCentimetres(distance: Double) {
        step()
        log.add("move ${distance.toInt()}")
        val ticks = round(abs(distance) / TICK_CM)
        val actual = ticks * TICK_CM * wobble(slip) * (if (distance < 0) -1 else 1)
        val r = Math.toRadians(heading)
        x += actual * sin(r)
        y += actual * cos(r)
    }

    override fun turnDegrees(angle: Double) {
        step()
        log.add("turn ${angle.toInt()}")
        val ticks = round(abs(angle) / TICK_DEGREES)
        heading += ticks * TICK_DEGREES * wobble(slip) * (if (angle < 0) -1 else 1)
    }

    private fun step() {
        if (++moves > failAfter) throw RobotError("move ended with STALLED")
    }

    override fun look(): List<Sighting> = plants.mapNotNull { (id, spot) ->
        val dx = spot.first - x
        val dy = spot.second - y
        val distance = hypot(dx, dy)
        var bearing = Math.toDegrees(atan2(dx, dy)) - heading
        while (bearing > 180) bearing -= 360
        while (bearing < -180) bearing += 360
        if (abs(bearing) > FIELD_OF_VIEW || distance > TAG_RANGE_CM) {
            null
        } else {
            Sighting(id, distance * wobble(noise), bearing + (random.nextDouble() * 2 - 1) * noise * 20)
        }
    }.sortedBy { it.distanceCm }

    fun distanceTo(plant: String) = plants.getValue(plant).let { hypot(it.first - x, it.second - y) }
}

/** Plays back scripted rule outcomes, and notes where the rover stood for each visit. */
private class FakeInspector(
    val field: Field,
    val script: List<Pair<String, String>> = listOf("healthy" to "move_on"),
) : Inspector {
    val visitDistances = ArrayList<Double>()
    val visits = ArrayList<String>()
    val marked = ArrayList<String>()

    override fun visit(plantId: String): VisitOutcome {
        visits.add(plantId)
        visitDistances.add(field.distanceTo(plantId))
        val (status, action) = script[minOf(visits.count { it == plantId } - 1, script.size - 1)]
        return VisitOutcome(status, "ACT_${visits.size}", action)
    }

    override fun markDone(plantId: String, actionId: String, note: String) {
        marked.add(note)
    }
}

class MissionTest {

    private val settings = MissionSettings()

    @Test
    fun visitsAPlantStraightAheadAndStopsAtTheStandoff() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 150.0)))
        val inspector = FakeInspector(field)

        val result = Mission(field, field, inspector).run()

        assertEquals(listOf("PLANT_001"), result.visited)
        assertEquals("finished", result.ending)
        assertEquals(40.0, inspector.visitDistances[0], settings.toleranceCm + TICK_CM)
    }

    @Test
    fun findsAPlantBehindItByTurning() {
        val field = Field(mapOf("PLANT_002" to (-60.0 to -120.0)))
        val inspector = FakeInspector(field)

        val result = Mission(field, field, inspector).run()

        assertEquals(listOf("PLANT_002"), result.visited)
        assertTrue(field.log.any { it.startsWith("turn") })
    }

    @Test
    fun visitsSeveralPlantsOnce() {
        val field = Field(mapOf("PLANT_001" to (30.0 to 140.0), "PLANT_002" to (-120.0 to 60.0), "PLANT_003" to (110.0 to -90.0)))
        val inspector = FakeInspector(field)

        val result = Mission(field, field, inspector).run()

        assertEquals(3, result.visited.size)
        assertEquals(3, result.visited.toSet().size)
    }

    @Test
    fun copesWithWheelSlipAndNoisyTags() {
        for (seed in 1L..200L) {
            val random = Random(seed)
            val plant = "PLANT_001" to ((random.nextDouble() * 300 - 150) to (random.nextDouble() * 300 - 150))
            if (hypot(plant.second.first, plant.second.second) < 70) continue
            val field = Field(mapOf(plant), seed, slip = 0.15, noise = 0.05)
            val inspector = FakeInspector(field)

            val result = Mission(field, field, inspector).run()

            if (hypot(plant.second.first, plant.second.second) < TAG_RANGE_CM - 30) {
                assertEquals("seed $seed", listOf("PLANT_001"), result.visited)
                assertEquals("seed $seed", 40.0, inspector.visitDistances[0], 15.0)
            }
        }
    }

    @Test
    fun finishesWhenThereAreNoTags() {
        val field = Field(emptyMap())

        val result = Mission(field, field, FakeInspector(field)).run()

        assertEquals("finished", result.ending)
        assertTrue(result.visited.isEmpty())
        assertEquals(12, field.log.size)
        assertFalse("must not drive when it sees nothing", field.log.any { it.startsWith("move") })
    }

    @Test
    fun neverDrivesForwardAfterMoveOn() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 100.0)))
        val inspector = FakeInspector(field)

        Mission(field, field, inspector).run()

        val afterVisit = field.log.dropWhile { it.startsWith("move") && !it.contains("-") }
        assertTrue(afterVisit.first(), afterVisit.first() == "move -25")
        assertTrue(field.distanceTo("PLANT_001") > 40)
    }

    @Test
    fun aSuspectedPlantGetsCloserViews() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 100.0)))
        val inspector = FakeInspector(
            field,
            listOf("suspected_disease" to "inspect_closer", "diseased" to "spray_plant"),
        )

        Mission(field, field, inspector).run()

        assertEquals(2, inspector.visits.size)
        assertTrue(inspector.visitDistances[1] < inspector.visitDistances[0])
        assertEquals(listOf("Moved 8 cm closer."), inspector.marked)
    }

    @Test
    fun sprayIsLeftOpenForAPerson() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 100.0)))
        val inspector = FakeInspector(field, listOf("diseased" to "spray_plant"))

        val result = Mission(field, field, inspector).run()

        assertEquals(listOf("PLANT_001"), result.visited)
        assertTrue("spray must not be closed by the mission", inspector.marked.isEmpty())
    }

    @Test
    fun viewsPerPlantAreLimited() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 100.0)))
        val inspector = FakeInspector(field, listOf("suspected_disease" to "inspect_closer"))

        Mission(field, field, inspector).run()

        assertEquals(settings.maxViews, inspector.visits.size)
    }

    @Test
    fun aRobotFailureEndsTheMission() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 200.0)))
        field.failAfter = 1

        val result = Mission(field, field, FakeInspector(field)).run()

        assertTrue(result.ending, "STALLED" in result.ending)
        assertEquals(2, field.moves)
    }

    @Test
    fun stopEndsTheMissionBeforeTheNextMove() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 200.0)))
        var stop = false
        val mover = object : Mover by field {
            override fun moveCentimetres(distance: Double) {
                field.moveCentimetres(distance)
                stop = true
            }
        }

        val result = Mission(mover, field, FakeInspector(field), stopRequested = { stop }).run()

        assertEquals(1, field.log.size)
        assertTrue(result.ending, "Stopped" in result.ending)
    }

    @Test
    fun aTagNotOnTheListIsNeverApproached() {
        val field = Field(mapOf("PLANT_017" to (0.0 to 120.0)))

        val result = Mission(field, field, FakeInspector(field), expected = setOf("PLANT_001")).run()

        assertTrue(result.visited.isEmpty())
        assertTrue(result.missed.isEmpty())
        assertTrue(field.log.none { it.startsWith("move") })
    }

    @Test
    fun listedPlantsAreVisitedAndOthersIgnored() {
        val field = Field(mapOf("PLANT_017" to (0.0 to 100.0), "PLANT_001" to (60.0 to 150.0)))

        val result = Mission(field, field, FakeInspector(field), expected = setOf("PLANT_001")).run()

        assertEquals(listOf("PLANT_001"), result.visited)
    }

    @Test
    fun plantListsAreRead() {
        assertEquals(
            setOf("PLANT_001", "PLANT_002", "PLANT_003", "PLANT_007"),
            parsePlantList(" 1-3, 7 "),
        )
        assertEquals(setOf("PLANT_000"), parsePlantList("0"))
    }

    @Test
    fun badPlantListsAreRefused() {
        for (text in listOf("", " , ", "abc", "5-1", "50", "1-2-3", "-1", "7,x")) {
            assertEquals(text, null, parsePlantList(text))
        }
    }

    @Test
    fun travelIsLimited() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 200.0)))

        val result = Mission(
            field, field, FakeInspector(field), MissionSettings(maxTravelCm = 50.0),
        ).run()

        assertEquals("travel limit reached", result.ending)
    }

    @Test
    fun aTagLostDuringApproachIsMissedNotChased() {
        val field = Field(mapOf("PLANT_001" to (0.0 to 200.0)))
        val fading = object : Eyes {
            var calls = 0
            override fun look() = if (++calls <= 1) field.look() else emptyList()
        }

        val result = Mission(field, fading, FakeInspector(field)).run()

        assertEquals(listOf("PLANT_001"), result.missed)
        assertTrue(result.visited.isEmpty())
    }
}
