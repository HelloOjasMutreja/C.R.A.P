package com.crap.speedtest

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.LocalDateTime
import java.util.UUID

/** One leaf the model found. Kept raw so diagnoses can be re-evaluated from the evidence. */
data class Detection(
    val rawClassName: String,
    val species: String,
    val condition: String,
    val isHealthy: Boolean,
    val confidence: Double,
    val bbox: List<Double>,
)

class Observation(
    val observationId: String,
    val timestamp: LocalDateTime,
    val imageReference: String?,
    val sensorReadings: Map<String, Double?>,
    val detections: List<Detection>,
)

class Diagnosis(
    val diagnosisId: String,
    val timestamp: LocalDateTime,
    val possibleCondition: String,
    val supportingEvidence: List<String>,
    val contradictingEvidence: List<String>,
    val confidence: Double?,
    val status: String,
    val observationIds: List<String>,
)

class Action(
    val actionId: String,
    val timestamp: LocalDateTime,
    val actionType: String,
    val reason: String,
    var status: String,
    var result: String? = null,
    var verificationObservationId: String? = null,
    var completedAt: LocalDateTime? = null,
)

class Plant(
    val plantId: String,
    val location: String,
    val createdAt: LocalDateTime,
    var species: String?,
    var currentStatus: String = "unassessed",
    val observations: MutableList<Observation> = ArrayList(),
    val diagnoses: MutableList<Diagnosis> = ArrayList(),
    val actions: MutableList<Action> = ArrayList(),
)

/** Every plant's history. Mirrors dossier/service.py; a null file keeps it in memory only. */
class PlantBook(
    private val file: File? = null,
    private val clock: () -> LocalDateTime = LocalDateTime::now,
    private val newId: (String) -> String = { prefix -> "${prefix}_${UUID.randomUUID().toString().take(8)}" },
) {
    private val plants = LinkedHashMap<String, Plant>()

    init {
        if (file != null && file.exists() && file.length() > 0) {
            val data = JSONArray(file.readText())
            for (i in 0 until data.length()) {
                val plant = plantFrom(data.getJSONObject(i))
                plants[plant.plantId] = plant
            }
        }
    }

    fun registerPlant(plantId: String, location: String, species: String? = null): Plant {
        require(plantId !in plants) { "Plant ID already exists: $plantId" }
        val plant = Plant(plantId, location, clock(), species)
        plants[plantId] = plant
        save()
        return plant
    }

    fun getPlant(plantId: String): Plant =
        plants[plantId] ?: throw IllegalArgumentException("Plant not found: $plantId")

    fun hasPlant(plantId: String) = plantId in plants

    fun listPlants(): List<Plant> = plants.values.toList()

    fun updatePlant(plantId: String, species: String? = null, currentStatus: String? = null): Plant {
        val plant = getPlant(plantId)
        if (species != null) plant.species = species
        if (currentStatus != null) plant.currentStatus = currentStatus
        save()
        return plant
    }

    fun submitObservation(
        plantId: String,
        imageReference: String? = null,
        sensorReadings: Map<String, Double?> = emptyMap(),
        detections: List<Detection> = emptyList(),
    ): Observation {
        val plant = getPlant(plantId)
        val observation = Observation(newId("OBS"), clock(), imageReference, sensorReadings, detections)
        plant.observations.add(observation)
        save()
        return observation
    }

    fun recordDiagnosis(
        plantId: String,
        possibleCondition: String,
        supportingEvidence: List<String>,
        contradictingEvidence: List<String>,
        confidence: Double?,
        status: String,
        observationIds: List<String>,
    ): Diagnosis {
        val plant = getPlant(plantId)
        val diagnosis = Diagnosis(
            newId("DIA"), clock(), possibleCondition, supportingEvidence,
            contradictingEvidence, confidence, status, observationIds,
        )
        plant.diagnoses.add(diagnosis)
        save()
        return diagnosis
    }

    fun recordAction(plantId: String, actionType: String, reason: String, status: String): Action {
        val plant = getPlant(plantId)
        val action = Action(newId("ACT"), clock(), actionType, reason, status)
        plant.actions.add(action)
        save()
        return action
    }

    fun getAction(plantId: String, actionId: String): Action =
        getPlant(plantId).actions.firstOrNull { it.actionId == actionId }
            ?: throw IllegalArgumentException("Action not found: $actionId")

    fun updateAction(
        plantId: String,
        actionId: String,
        status: String? = null,
        result: String? = null,
        verificationObservationId: String? = null,
        completedAt: LocalDateTime? = null,
    ): Action {
        val action = getAction(plantId, actionId)
        if (status != null) action.status = status
        if (result != null) action.result = result
        if (verificationObservationId != null) action.verificationObservationId = verificationObservationId
        if (completedAt != null) action.completedAt = completedAt
        save()
        return action
    }

    /** Write to a temporary file first, so a crash or dead battery cannot corrupt the records. */
    private fun save() {
        val target = file ?: return
        val data = JSONArray()
        plants.values.forEach { data.put(plantJson(it)) }
        target.parentFile?.mkdirs()
        val temporary = File(target.path + ".tmp")
        temporary.writeText(data.toString())
        check(temporary.renameTo(target)) { "Could not save plant records" }
    }

    private fun plantJson(plant: Plant) = JSONObject()
        .put("plant_id", plant.plantId)
        .put("location", plant.location)
        .put("created_at", plant.createdAt.toString())
        .put("species", plant.species ?: JSONObject.NULL)
        .put("current_status", plant.currentStatus)
        .put("observations", JSONArray(plant.observations.map(::observationJson)))
        .put("diagnoses", JSONArray(plant.diagnoses.map(::diagnosisJson)))
        .put("actions", JSONArray(plant.actions.map(::actionJson)))

    private fun observationJson(o: Observation): JSONObject {
        val readings = JSONObject()
        o.sensorReadings.forEach { (key, value) -> readings.put(key, value ?: JSONObject.NULL) }
        return JSONObject()
            .put("observation_id", o.observationId)
            .put("timestamp", o.timestamp.toString())
            .put("image_reference", o.imageReference ?: JSONObject.NULL)
            .put("sensor_readings", readings)
            .put("detections", JSONArray(o.detections.map(::detectionJson)))
    }

    private fun detectionJson(d: Detection) = JSONObject()
        .put("raw_class_name", d.rawClassName)
        .put("species", d.species)
        .put("condition", d.condition)
        .put("is_healthy", d.isHealthy)
        .put("confidence", d.confidence)
        .put("bbox", JSONArray(d.bbox))

    private fun diagnosisJson(d: Diagnosis) = JSONObject()
        .put("diagnosis_id", d.diagnosisId)
        .put("timestamp", d.timestamp.toString())
        .put("possible_condition", d.possibleCondition)
        .put("supporting_evidence", JSONArray(d.supportingEvidence))
        .put("contradicting_evidence", JSONArray(d.contradictingEvidence))
        .put("confidence", d.confidence ?: JSONObject.NULL)
        .put("status", d.status)
        .put("observation_ids", JSONArray(d.observationIds))

    private fun actionJson(a: Action) = JSONObject()
        .put("action_id", a.actionId)
        .put("timestamp", a.timestamp.toString())
        .put("action_type", a.actionType)
        .put("reason", a.reason)
        .put("status", a.status)
        .put("result", a.result ?: JSONObject.NULL)
        .put("verification_observation_id", a.verificationObservationId ?: JSONObject.NULL)
        .put("completed_at", a.completedAt?.toString() ?: JSONObject.NULL)

    private fun plantFrom(json: JSONObject) = Plant(
        plantId = json.getString("plant_id"),
        location = json.getString("location"),
        createdAt = LocalDateTime.parse(json.getString("created_at")),
        species = json.textOrNull("species"),
        currentStatus = json.getString("current_status"),
        observations = json.getJSONArray("observations").objects().map(::observationFrom).toMutableList(),
        diagnoses = json.getJSONArray("diagnoses").objects().map(::diagnosisFrom).toMutableList(),
        actions = json.getJSONArray("actions").objects().map(::actionFrom).toMutableList(),
    )

    private fun observationFrom(json: JSONObject): Observation {
        val readings = LinkedHashMap<String, Double?>()
        val stored = json.getJSONObject("sensor_readings")
        stored.keys().forEach { key -> readings[key] = if (stored.isNull(key)) null else stored.getDouble(key) }
        return Observation(
            json.getString("observation_id"),
            LocalDateTime.parse(json.getString("timestamp")),
            json.textOrNull("image_reference"),
            readings,
            json.getJSONArray("detections").objects().map(::detectionFrom),
        )
    }

    private fun detectionFrom(json: JSONObject): Detection {
        val box = json.getJSONArray("bbox")
        return Detection(
            json.getString("raw_class_name"),
            json.getString("species"),
            json.getString("condition"),
            json.getBoolean("is_healthy"),
            json.getDouble("confidence"),
            (0 until box.length()).map { box.getDouble(it) },
        )
    }

    private fun diagnosisFrom(json: JSONObject) = Diagnosis(
        json.getString("diagnosis_id"),
        LocalDateTime.parse(json.getString("timestamp")),
        json.getString("possible_condition"),
        json.getJSONArray("supporting_evidence").strings(),
        json.getJSONArray("contradicting_evidence").strings(),
        if (json.isNull("confidence")) null else json.getDouble("confidence"),
        json.getString("status"),
        json.getJSONArray("observation_ids").strings(),
    )

    private fun actionFrom(json: JSONObject) = Action(
        json.getString("action_id"),
        LocalDateTime.parse(json.getString("timestamp")),
        json.getString("action_type"),
        json.getString("reason"),
        json.getString("status"),
        json.textOrNull("result"),
        json.textOrNull("verification_observation_id"),
        json.textOrNull("completed_at")?.let(LocalDateTime::parse),
    )

    private fun JSONObject.textOrNull(key: String): String? = if (isNull(key)) null else getString(key)

    private fun JSONArray.objects() = (0 until length()).map { getJSONObject(it) }

    private fun JSONArray.strings() = (0 until length()).map { getString(it) }
}
