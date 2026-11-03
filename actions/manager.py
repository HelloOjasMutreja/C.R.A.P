from typing import Optional

from dossier import DossierService
from hardware import RobotError, SimulatedRobot

# What to do for each plant status. Every action is recorded with its reason.
DECISIONS = {
    "suspected_disease": "inspect_closer",
    "diseased": "flag_plant",
    "needs_reinspection": "reposition_and_retry",
    "healthy": "move_on",
}

# The robot commands each action runs, in order.
PLANS = {
    "inspect_closer": [("arm", "inspect")],
    "flag_plant": [("arm", "flag"), ("arm", "home")],
    "reposition_and_retry": [("drive", "back", 300)],
    "move_on": [("arm", "home"), ("drive", "forward", 1000)],
}

# Actions that touch the plant wait for a person to approve them.
NEEDS_APPROVAL = {"flag_plant"}

# Actions whose effect is checked by the next recorded visit.
VERIFIED_BY_NEXT_VISIT = {"inspect_closer", "reposition_and_retry"}

OPEN_STATUSES = ("proposed", "awaiting_approval", "approved")


class ActionManager:
    """Turns a plant's diagnosed status into one recorded, explainable robot action.

    Lifecycle: proposed (or awaiting_approval -> approved) -> completed / failed,
    or superseded / rejected. Actions are only carried out when ``execute`` is
    called, so a person or the demo flow stays in control of the robot.
    """

    def __init__(self, service: Optional[DossierService] = None, robot=None):
        self.service = service if service is not None else DossierService()
        self.robot = robot if robot is not None else SimulatedRobot()

    def propose(self, plant_id: str):
        """Record the next action for the plant's current status, or return None if there is none."""
        plant = self.service.get_plant(plant_id)
        action_type = DECISIONS.get(plant.current_status)
        if action_type is None:
            return None

        # Keep one open action per plant: reuse a matching one, retire the rest.
        for action in plant.actions:
            if action.status not in OPEN_STATUSES:
                continue
            if action.action_type == action_type:
                return action
            self.service.update_action(
                plant_id,
                action.action_id,
                status="superseded",
                result=f"Replaced by {action_type} after status became {plant.current_status}.",
            )

        return self.service.record_action(
            plant_id=plant_id,
            action_type=action_type,
            reason=self._reason(plant, action_type),
            status="awaiting_approval" if action_type in NEEDS_APPROVAL else "proposed",
        )

    def approve(self, plant_id: str, action_id: str):
        action = self.service.get_action(plant_id, action_id)
        if action.status != "awaiting_approval":
            raise ValueError(f"{action_id} is {action.status}, not awaiting approval")
        return self.service.update_action(plant_id, action_id, status="approved")

    def reject(self, plant_id: str, action_id: str):
        action = self.service.get_action(plant_id, action_id)
        if action.status not in OPEN_STATUSES:
            raise ValueError(f"{action_id} is already {action.status}")
        return self.service.update_action(
            plant_id, action_id, status="rejected", result="Rejected by operator."
        )

    def execute(self, plant_id: str, action_id: str):
        """Run the action's robot commands. On any failure the robot is stopped."""
        action = self.service.get_action(plant_id, action_id)
        if action.status == "awaiting_approval":
            raise ValueError(f"{action.action_type} needs approval before it can run")
        if action.status not in ("proposed", "approved"):
            raise ValueError(f"{action_id} is {action.status} and cannot run")

        done = []
        try:
            for step in PLANS[action.action_type]:
                if step[0] == "arm":
                    self.robot.arm(step[1])
                    done.append(f"arm → {step[1]}")
                else:
                    self.robot.drive(step[1], step[2])
                    done.append(f"drive {step[1]} {step[2]} ms")
        except RobotError as err:
            try:
                self.robot.stop()
            except RobotError:
                pass
            steps = "; ".join(done) or "nothing"
            return self.service.update_action(
                plant_id,
                action_id,
                status="failed",
                result=f"Stopped after: {steps}. Error: {err}",
            )

        result = "; ".join(done) + "."
        if action.action_type in VERIFIED_BY_NEXT_VISIT:
            result += " Record a visit to verify."
        return self.service.update_action(plant_id, action_id, status="completed", result=result)

    def link_verification(self, plant_id: str, observation_id: str) -> list:
        """Attach a new observation to completed actions that were waiting for one."""
        plant = self.service.get_plant(plant_id)
        linked = []

        for action in plant.actions:
            if (
                action.status == "completed"
                and action.action_type in VERIFIED_BY_NEXT_VISIT
                and action.verification_observation_id is None
            ):
                result = (action.result or "").replace(" Record a visit to verify.", "")
                linked.append(
                    self.service.update_action(
                        plant_id,
                        action.action_id,
                        result=f"{result} Verified by {observation_id}.".strip(),
                        verification_observation_id=observation_id,
                    )
                )

        return linked

    def _reason(self, plant, action_type: str) -> str:
        latest = plant.observations[-1].observation_id if plant.observations else None
        current = [d for d in plant.diagnoses if d.observation_ids and d.observation_ids[0] == latest]
        current.sort(key=lambda d: (d.status == "confirmed", d.confidence or 0), reverse=True)
        top = current[0] if current else None
        found = f"{top.possible_condition} ({(top.confidence or 0):.0%})" if top else "A condition"

        if action_type == "inspect_closer":
            return f"{found} is suspected from one sighting; a closer look can confirm or rule it out."
        if action_type == "flag_plant":
            return f"{found} is confirmed on repeat visits; mark the plant for treatment."
        if action_type == "reposition_and_retry":
            return "No usable leaves were in view; move slightly and look again."
        return "No disease seen; continue to the next plant."
