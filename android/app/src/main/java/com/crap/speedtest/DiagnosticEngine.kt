package com.crap.speedtest

import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToLong

// Detections this similar come from effectively the same frame.
private const val SAME_VIEW_OVERLAP = 0.9
private const val SAME_VIEW_CONFIDENCE = 0.03

// A plant in one of these states keeps it when a frame shows no usable leaves.
private val AT_RISK = setOf("diseased", "suspected_disease", "uncertain")

// High humidity only adds context to a condition the camera already saw.
private val HUMIDITY_FAVOURED = setOf(
    "Apple Scab", "Apple Rust", "Black Rot", "Common Rust", "Early Blight",
    "Gray Leaf Spot", "Late Blight", "Leaf Blight", "Leaf Mold", "Septoria Leaf Spot",
)

data class EngineResult(
    val plantId: String,
    val observationId: String?,
    val plantStatus: String,
    val diagnoses: List<Diagnosis> = emptyList(),
    val notes: List<String> = emptyList(),
)

fun percent(value: Double): String = String.format(Locale.ROOT, "%.0f%%", value * 100)

private fun boxOverlap(a: List<Double>, b: List<Double>): Double {
    val width = min(a[2], b[2]) - max(a[0], b[0])
    val height = min(a[3], b[3]) - max(a[1], b[1])
    if (width <= 0 || height <= 0) return 0.0
    val overlap = width * height
    val areaA = (a[2] - a[0]) * (a[3] - a[1])
    val areaB = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (areaA + areaB - overlap)
}

/** True when two observations are effectively the same frame, so not a new sighting. */
private fun sameView(first: Observation, second: Observation): Boolean {
    if (first.imageReference != null && first.imageReference.isNotEmpty() &&
        first.imageReference == second.imageReference
    ) {
        return true
    }
    if (first.detections.isEmpty() || first.detections.size != second.detections.size) return false

    val unmatched = second.detections.toMutableList()
    for (a in first.detections) {
        val index = unmatched.indexOfFirst { b ->
            a.condition == b.condition &&
                a.species == b.species &&
                abs(a.confidence - b.confidence) <= SAME_VIEW_CONFIDENCE &&
                boxOverlap(a.bbox, b.bbox) >= SAME_VIEW_OVERLAP
        }
        if (index < 0) return false
        unmatched.removeAt(index)
    }
    return true
}

/** Turns observations into suspected or confirmed conditions. Port of diagnostics/engine.py. */
class DiagnosticEngine(
    private val book: PlantBook,
    private val minConfidence: Double = 0.35,
    private val confirmConfidence: Double = 0.60,
    private val lookback: Int = 3,
    private val highHumidity: Double = 70.0,
) {

    fun evaluate(plantId: String, observationId: String? = null): EngineResult {
        val plant = book.getPlant(plantId)

        if (plant.observations.isEmpty()) {
            return EngineResult(plantId, null, plant.currentStatus, notes = listOf("No observations recorded yet."))
        }

        val index = observationIndex(plant, observationId)
        val target = plant.observations[index]
        val isLatest = index == plant.observations.size - 1

        // Evaluating the same observation twice should not duplicate diagnoses.
        val existing = plant.diagnoses.filter { it.observationIds.firstOrNull() == target.observationId }
        if (existing.isNotEmpty()) {
            return EngineResult(
                plantId, target.observationId, plant.currentStatus, existing,
                listOf("${target.observationId} was already evaluated."),
            )
        }

        val notes = ArrayList<String>()
        val species = plant.species ?: dominantSpecies(target)
        val relevant = relevant(target, species)

        val offSpecies = target.detections.filter { it.species != species && it.confidence >= minConfidence }
        if (offSpecies.isNotEmpty()) {
            val names = offSpecies.map { it.rawClassName }.toSortedSet().joinToString(", ")
            notes.add("Ignored ${offSpecies.size} detection(s) of other species ($names); the plant is recorded as $species.")
        }

        if (relevant.isEmpty()) {
            notes.add(
                "No ${species ?: "plant"} leaves detected at ${percent(minConfidence)} confidence " +
                    "or higher in ${target.observationId}.",
            )
            // A bad frame says nothing about a plant already under suspicion.
            val status = if (plant.currentStatus in AT_RISK) plant.currentStatus else "needs_reinspection"
            return finish(plantId, target, status, emptyList(), notes, isLatest)
        }

        val (views, repeated) = distinctViews(plant, index, species)
        if (repeated) {
            notes.add(
                "This looks like the same view as an earlier visit, so it is not a new " +
                    "sighting. Move or zoom in for a second opinion.",
            )
        }

        val votes = LinkedHashMap<String, Int>()
        for (view in views) {
            for (condition in conditions(view, species, confirmConfidence).keys) {
                votes[condition] = (votes[condition] ?: 0) + 1
            }
        }

        val most = votes.values.maxOrNull() ?: 0
        val leaders = votes.filterValues { it == most }.keys.sorted()
        val conflict = most >= 2 && leaders.size > 1
        val confirmed = if (most >= 2 && leaders.size == 1 && most * 2 > views.size) leaders[0] else null

        val active = LinkedHashSet(conditions(target, species, minConfidence).keys)
        votes.filterValues { it * 2 >= views.size }.keys.forEach { active.add(it) }
        if (confirmed != null || conflict) active.addAll(votes.keys)

        if (conflict) {
            notes.add("${leaders.joinToString(" and ")} are tied at $most views each, so a person should decide.")
        }

        val ordered = active.sortedWith(compareBy({ -(votes[it] ?: 0) }, { it }))
        val diagnoses = ordered.map { condition ->
            diagnose(
                plantId, species!!, condition, relevant, target, views, votes[condition] ?: 0,
                if (condition == confirmed) "confirmed" else "suspected",
            )
        }

        val status = when {
            confirmed != null -> "diseased"
            conflict -> "uncertain"
            active.isNotEmpty() -> "suspected_disease"
            else -> "healthy"
        }
        return finish(plantId, target, status, diagnoses, notes, isLatest)
    }

    private fun diagnose(
        plantId: String,
        species: String,
        condition: String,
        relevant: List<Detection>,
        target: Observation,
        views: List<Observation>,
        voteCount: Int,
        status: String,
    ): Diagnosis {
        val group = relevant.filter { !it.isHealthy && it.condition == condition }
        val healthy = relevant.filter { it.isHealthy }
        val earlier = views.asReversed().filter { it !== target }

        val supporting = ArrayList<String>()
        val contradicting = ArrayList<String>()
        val observationIds = arrayListOf(target.observationId)
        val confidences = ArrayList(group.map { it.confidence })

        if (group.isNotEmpty()) {
            supporting.add(
                "${group.size} $species leaf detection(s) show $condition in ${target.observationId} " +
                    "(highest confidence ${percent(confidences.max())}).",
            )
        } else {
            contradicting.add("Not detected in the latest observation ${target.observationId}.")
        }

        if (healthy.isNotEmpty()) {
            contradicting.add("${healthy.size} healthy $species leaf detection(s) in the same image.")
        }

        val humidity = target.sensorReadings["humidity_rh"]
        if (humidity != null && humidity >= highHumidity && condition in HUMIDITY_FAVOURED) {
            val shown = String.format(Locale.ROOT, "%.0f", humidity)
            supporting.add("Air humidity was $shown%, which favours $condition; context only.")
        }

        for (view in earlier) {
            val seen = conditions(view, species, minConfidence)[condition]
            if (seen != null) {
                supporting.add(
                    "Also detected in earlier observation ${view.observationId} " +
                        "(highest confidence ${percent(seen)}).",
                )
                observationIds.add(view.observationId)
                confidences.add(seen)
            } else {
                contradicting.add("Not detected in earlier observation ${view.observationId}.")
            }
        }

        if (views.size > 1) {
            supporting.add("Seen clearly in $voteCount of ${views.size} distinct views.")
        } else if (status != "confirmed") {
            supporting.add("First observation of this plant; a repeat observation is needed to confirm.")
        }

        return book.recordDiagnosis(
            plantId,
            "$species $condition",
            supporting,
            contradicting,
            (confidences.max() * 10000).roundToLong() / 10000.0,
            status,
            observationIds,
        )
    }

    private fun finish(
        plantId: String,
        target: Observation,
        status: String,
        diagnoses: List<Diagnosis>,
        notes: List<String>,
        isLatest: Boolean,
    ): EngineResult {
        // Looking back at an old visit must not overwrite what is true today.
        val shown = if (isLatest) {
            book.updatePlant(plantId, currentStatus = status)
            status
        } else {
            book.getPlant(plantId).currentStatus
        }
        return EngineResult(plantId, target.observationId, shown, diagnoses, notes)
    }

    /** The usable, distinct observations in the evidence window, oldest first. */
    private fun distinctViews(plant: Plant, index: Int, species: String?): Pair<List<Observation>, Boolean> {
        val since = plant.actions
            .filter { it.actionType == "spray_plant" && it.status == "completed" }
            .mapNotNull { it.completedAt }
            .maxOrNull()

        val views = ArrayList<Observation>()
        var repeated = false
        for (observation in plant.observations.subList(0, index + 1)) {
            if (since != null && !observation.timestamp.isAfter(since)) continue
            if (relevant(observation, species).isEmpty()) continue
            if (views.any { sameView(it, observation) }) {
                repeated = observation === plant.observations[index]
                continue
            }
            views.add(observation)
        }
        return Pair(views.takeLast(lookback + 1), repeated)
    }

    /** Highest confidence of each disease on this plant at or above threshold. */
    private fun conditions(observation: Observation, species: String?, threshold: Double): Map<String, Double> {
        val found = LinkedHashMap<String, Double>()
        for (d in relevant(observation, species)) {
            if (!d.isHealthy && d.confidence >= threshold) {
                found[d.condition] = max(found[d.condition] ?: 0.0, d.confidence)
            }
        }
        return found
    }

    private fun relevant(observation: Observation, species: String?) =
        observation.detections.filter { it.species == species && it.confidence >= minConfidence }

    private fun dominantSpecies(observation: Observation): String? =
        observation.detections
            .filter { it.confidence >= minConfidence }
            .groupingBy { it.species }
            .eachCount()
            .entries
            .maxByOrNull { it.value }
            ?.key

    private fun observationIndex(plant: Plant, observationId: String?): Int {
        if (observationId == null) return plant.observations.size - 1
        val index = plant.observations.indexOfFirst { it.observationId == observationId }
        require(index >= 0) { "Observation not found: $observationId" }
        return index
    }
}
