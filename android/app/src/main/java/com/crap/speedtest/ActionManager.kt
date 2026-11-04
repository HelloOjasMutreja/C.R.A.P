package com.crap.speedtest

import java.time.Duration
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

class RobotError(message: String) : Exception(message)

/** What the action manager needs from the rover. Bluetooth comes later; see SimulatedRobot. */
interface Robot {
    val hasArm: Boolean
    fun arm(pose: String)
    fun spray(ms: Int)
    fun drive(command: String, ms: Int)
    fun stop()
}

/** Records commands instead of moving anything. [failOn] makes chosen commands fail. */
class SimulatedRobot(
    override val hasArm: Boolean = true,
    private val failOn: Set<String> = emptySet(),
) : Robot {
    val log = ArrayList<String>()

    override fun arm(pose: String) {
        if (pose in failOn) throw RobotError("Simulated failure on arm $pose")
        log.add("arm $pose")
    }

    override fun spray(ms: Int) {
        if ("spray_trigger" in failOn) throw RobotError("Simulated failure on spray")
        log.add("spray $ms")
    }

    override fun drive(command: String, ms: Int) {
        if (command in failOn) throw RobotError("Simulated failure on drive $command")
        log.add("drive $command $ms")
    }

    override fun stop() {
        log.add("drive stop 0")
    }
}

private sealed class Step {
    data class Arm(val pose: String) : Step()
    data class Spray(val ms: Int) : Step()
    data class Drive(val command: String, val ms: Int) : Step()
}

private val DECISIONS = mapOf(
    "suspected_disease" to "inspect_closer",
    "diseased" to "spray_plant",
    "needs_reinspection" to "reposition_and_retry",
    "uncertain" to "request_review",
    "healthy" to "move_on",
)

private val PLANS = mapOf(
    "inspect_closer" to listOf(Step.Arm("inspect")),
    "spray_plant" to listOf(Step.Arm("spray"), Step.Spray(500), Step.Arm("home")),
    "reposition_and_retry" to listOf(Step.Drive("back", 300)),
    "move_on" to listOf(Step.Arm("home"), Step.Drive("forward", 1000)),
    "request_review" to emptyList(),
)

// Actions that touch the plant wait for a person to approve them.
private val NEEDS_APPROVAL = setOf("spray_plant")

// Actions whose effect is checked by the next recorded visit.
private val VERIFIED_BY_NEXT_VISIT = setOf("inspect_closer", "reposition_and_retry")

private val OPEN_STATUSES = setOf("proposed", "awaiting_approval", "approved")

// The robot gives up and asks a person after this many of the same action in a row.
private const val MAX_REPEATS = 2

// Time for a treatment to show before the plant may be judged again. Provisional.
private val SPRAY_COOLDOWN: Duration = Duration.ofHours(72)

private const val VERIFY_NOTE = " Record a visit to verify."
private val SPRAY_TIME = DateTimeFormatter.ofPattern("dd MMM 'at' HH:mm", Locale.ENGLISH)

/** Turns a plant's status into one recorded, explainable action. Port of actions/manager.py. */
class ActionManager(
    private val book: PlantBook,
    private val robot: Robot,
    private val clock: () -> LocalDateTime = LocalDateTime::now,
) {

    /** Record the next action for the plant's current status, or return null if there is none. */
    fun propose(plantId: String): Action? {
        val plant = book.getPlant(plantId)
        val wanted = DECISIONS[plant.currentStatus] ?: return null
        val (actionType, specialReason) = applyLimits(plant, wanted)

        // Keep one open action per plant: reuse a matching one, retire the rest.
        for (action in plant.actions.toList()) {
            if (action.status !in OPEN_STATUSES) continue
            if (action.actionType == actionType) return action
            book.updateAction(
                plantId,
                action.actionId,
                status = "superseded",
                result = "Replaced by $actionType after status became ${plant.currentStatus}.",
            )
        }

        return book.recordAction(
            plantId,
            actionType,
            specialReason ?: reason(plant, actionType),
            if (actionType in NEEDS_APPROVAL) "awaiting_approval" else "proposed",
        )
    }

    fun approve(plantId: String, actionId: String): Action {
        val action = book.getAction(plantId, actionId)
        require(action.status == "awaiting_approval") { "$actionId is ${action.status}, not awaiting approval" }
        return book.updateAction(plantId, actionId, status = "approved")
    }

    fun reject(plantId: String, actionId: String): Action {
        val action = book.getAction(plantId, actionId)
        require(action.status in OPEN_STATUSES) { "$actionId is already ${action.status}" }
        return book.updateAction(plantId, actionId, status = "rejected", result = "Rejected by operator.")
    }

    /** Run the action's robot commands. On any failure the robot is stopped. */
    fun execute(plantId: String, actionId: String): Action {
        val action = book.getAction(plantId, actionId)
        require(action.status != "awaiting_approval") { "${action.actionType} needs approval before it can run" }
        require(action.status == "proposed" || action.status == "approved") {
            "$actionId is ${action.status} and cannot run"
        }

        val done = ArrayList<String>()
        try {
            for (step in PLANS.getValue(action.actionType)) {
                when (step) {
                    is Step.Arm -> {
                        // A robot without an arm is already "home"; any other arm step must fail.
                        if (step.pose == "home" && !robot.hasArm) continue
                        robot.arm(step.pose)
                        done.add("arm → ${step.pose}")
                    }
                    is Step.Spray -> {
                        robot.spray(step.ms)
                        done.add("spray ${step.ms} ms")
                    }
                    is Step.Drive -> {
                        robot.drive(step.command, step.ms)
                        done.add("drive ${step.command} ${step.ms} ms")
                    }
                }
            }
        } catch (error: RobotError) {
            try {
                robot.stop()
            } catch (_: RobotError) {
                // Already failing; the failure below is what gets reported.
            }
            val steps = if (done.isEmpty()) "nothing" else done.joinToString("; ")
            return book.updateAction(
                plantId, actionId, status = "failed", result = "Stopped after: $steps. Error: ${error.message}",
            )
        }

        var result = if (done.isEmpty()) "Reviewed by operator." else done.joinToString("; ") + "."
        if (action.actionType in VERIFIED_BY_NEXT_VISIT) result += VERIFY_NOTE
        return book.updateAction(plantId, actionId, status = "completed", result = result, completedAt = clock())
    }

    /** Attach a new observation to completed actions that were waiting for one. */
    fun linkVerification(plantId: String, observationId: String): List<Action> {
        val linked = ArrayList<Action>()
        for (action in book.getPlant(plantId).actions) {
            if (action.status == "completed" &&
                action.actionType in VERIFIED_BY_NEXT_VISIT &&
                action.verificationObservationId == null
            ) {
                val result = (action.result ?: "").replace(VERIFY_NOTE, "")
                linked.add(
                    book.updateAction(
                        plantId,
                        action.actionId,
                        result = "$result Verified by $observationId.".trim(),
                        verificationObservationId = observationId,
                    ),
                )
            }
        }
        return linked
    }

    /** Stop the robot repeating itself; return the action to use and any special reason. */
    private fun applyLimits(plant: Plant, actionType: String): Pair<String, String?> {
        if (actionType == "spray_plant") {
            val last = plant.actions
                .filter { it.actionType == "spray_plant" && it.status == "completed" }
                .mapNotNull { it.completedAt }
                .maxOrNull()
            if (last != null) {
                if (Duration.between(last, clock()) < SPRAY_COOLDOWN) {
                    return Pair(
                        "move_on",
                        "This plant was sprayed on ${last.format(SPRAY_TIME)}; " +
                            "give the treatment time before judging it again.",
                    )
                }
                return Pair(
                    "request_review",
                    "The disease is still present after treatment; a person should decide what to do next.",
                )
            }
        }

        if (actionType == "inspect_closer" || actionType == "reposition_and_retry") {
            val streak = plant.actions
                .filter { it.status == "completed" }
                .asReversed()
                .takeWhile { it.actionType == actionType }
                .size
            if (streak >= MAX_REPEATS) {
                return Pair("request_review", "$streak attempts in a row did not settle this plant; a person should look at it.")
            }
        }

        return Pair(actionType, null)
    }

    private fun reason(plant: Plant, actionType: String): String {
        val latest = plant.observations.lastOrNull()?.observationId
        val current = plant.diagnoses
            .filter { it.observationIds.firstOrNull() == latest }
            .sortedWith(compareBy<Diagnosis>({ it.status != "confirmed" }, { -(it.confidence ?: 0.0) }))
        val top = current.firstOrNull()
        val found = if (top != null) "${top.possibleCondition} (${percent(top.confidence ?: 0.0)})" else "A condition"

        return when (actionType) {
            "inspect_closer" -> "$found is suspected from one sighting; a closer look can confirm or rule it out."
            "spray_plant" -> "$found is confirmed on repeat visits; spray the plant once approved."
            "reposition_and_retry" -> "No usable leaves were in view; move slightly and look again."
            "request_review" -> {
                val names = current.joinToString(" and ") { it.possibleCondition }
                "The views disagree between $names; a person should decide before any treatment."
            }
            else -> "No disease seen; continue to the next plant."
        }
    }
}
