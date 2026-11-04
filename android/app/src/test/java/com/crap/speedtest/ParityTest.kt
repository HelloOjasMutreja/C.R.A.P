package com.crap.speedtest

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.LocalDateTime

/** Replays histories recorded from the Python rules; see android/make_parity_fixtures.py. */
class ParityTest {

    private fun strings(array: JSONArray) = (0 until array.length()).map { array.getString(it) }

    private fun detections(array: JSONArray) = (0 until array.length()).map { i ->
        val d = array.getJSONObject(i)
        val box = d.getJSONArray("bbox")
        Detection(
            d.getString("raw_class_name"),
            d.getString("species"),
            d.getString("condition"),
            d.getBoolean("is_healthy"),
            d.getDouble("confidence"),
            (0 until box.length()).map { box.getDouble(it) },
        )
    }

    private fun textOrNull(json: JSONObject, key: String) = if (json.isNull(key)) null else json.getString(key)

    private fun play(scenario: JSONObject, where: String) {
        var now = LocalDateTime.of(2026, 1, 1, 8, 0)
        var ids = 0
        val book = PlantBook(clock = { now }, newId = { prefix -> "${prefix}_${++ids}" })
        val engine = DiagnosticEngine(book)
        val robot = SimulatedRobot(scenario.getBoolean("has_arm"), strings(scenario.getJSONArray("fail_on")).toSet())
        val manager = ActionManager(book, robot, clock = { now })
        book.registerPlant("P", "A1", textOrNull(scenario, "species"))

        val steps = scenario.getJSONArray("steps")
        for (s in 0 until steps.length()) {
            val step = steps.getJSONObject(s)
            val at = "$where visit $s"
            now = now.plusHours(step.getLong("hours"))

            val readings = if (step.isNull("humidity")) {
                emptyMap()
            } else {
                mapOf<String, Double?>("humidity_rh" to step.getDouble("humidity"))
            }
            val observation = book.submitObservation(
                "P", textOrNull(step, "image"), readings, detections(step.getJSONArray("detections")),
            )
            val result = engine.evaluate("P", observation.observationId)
            manager.linkVerification("P", observation.observationId)
            val action = manager.propose("P")

            when (step.getString("op")) {
                "reject" -> if (action != null) manager.reject("P", action.actionId)
                "run" -> if (action != null) {
                    if (action.status == "awaiting_approval") manager.approve("P", action.actionId)
                    manager.execute("P", action.actionId)
                }
            }

            assertEquals("$at status", step.getString("status"), result.plantStatus)
            assertEquals("$at plant status", step.getString("plant_status"), book.getPlant("P").currentStatus)
            assertEquals("$at notes", strings(step.getJSONArray("notes")), result.notes)

            val expected = step.getJSONArray("diagnoses")
            assertEquals("$at diagnosis count", expected.length(), result.diagnoses.size)
            for (i in 0 until expected.length()) {
                val want = expected.getJSONObject(i)
                val got = result.diagnoses[i]
                assertEquals("$at condition", want.getString("condition"), got.possibleCondition)
                assertEquals("$at diagnosis status", want.getString("status"), got.status)
                assertEquals("$at confidence", want.getDouble("confidence"), got.confidence!!, 1e-9)
                assertEquals("$at supporting", strings(want.getJSONArray("supporting")), got.supportingEvidence)
                assertEquals("$at contradicting", strings(want.getJSONArray("contradicting")), got.contradictingEvidence)
                assertEquals("$at observations", strings(want.getJSONArray("observations")), got.observationIds)
            }

            val actions = step.getJSONArray("actions")
            val plantActions = book.getPlant("P").actions
            assertEquals("$at action count", actions.length(), plantActions.size)
            for (i in 0 until actions.length()) {
                val want = actions.getJSONObject(i)
                val got = plantActions[i]
                assertEquals("$at action id", want.getString("id"), got.actionId)
                assertEquals("$at action type", want.getString("type"), got.actionType)
                assertEquals("$at action status", want.getString("status"), got.status)
                assertEquals("$at action reason", want.getString("reason"), got.reason)
                assertEquals("$at action result", textOrNull(want, "result"), got.result)
                assertEquals("$at verification", textOrNull(want, "verification"), got.verificationObservationId)
            }

            assertEquals("$at robot", strings(step.getJSONArray("robot")), robot.log)
        }
    }

    @Test
    fun kotlinMatchesPythonOnEveryRecordedHistory() {
        val text = javaClass.classLoader!!.getResourceAsStream("decision_scenarios.json")!!
            .bufferedReader(Charsets.UTF_8).readText()
        val scenarios = JSONArray(text)
        assertTrue("fixtures are present", scenarios.length() > 100)
        for (i in 0 until scenarios.length()) {
            play(scenarios.getJSONObject(i), "scenario $i")
        }
    }

    @Test
    fun recordsSurviveARestart() {
        val folder = Files.createTempDirectory("plants").toFile()
        val file = File(folder, "plants.json")

        val book = PlantBook(file)
        book.registerPlant("PLANT_001", "Bed A1", "Tomato")
        val leaf = Detection("Tomato Early Blight", "Tomato", "Early Blight", false, 0.82, listOf(0.0, 0.0, 9.0, 9.0))
        val observation = book.submitObservation("PLANT_001", "a.jpg", mapOf("humidity_rh" to 75.0), listOf(leaf))
        DiagnosticEngine(book).evaluate("PLANT_001", observation.observationId)
        val manager = ActionManager(book, SimulatedRobot())
        val action = manager.propose("PLANT_001")!!
        manager.execute("PLANT_001", action.actionId)

        val reopened = PlantBook(file).getPlant("PLANT_001")

        assertEquals("Tomato", reopened.species)
        assertEquals("suspected_disease", reopened.currentStatus)
        assertEquals(leaf, reopened.observations[0].detections[0])
        assertEquals(75.0, reopened.observations[0].sensorReadings["humidity_rh"]!!, 0.0)
        assertEquals("suspected", reopened.diagnoses[0].status)
        assertEquals("completed", reopened.actions[0].status)
        assertEquals(action.completedAt, reopened.actions[0].completedAt)
        folder.deleteRecursively()
    }
}
