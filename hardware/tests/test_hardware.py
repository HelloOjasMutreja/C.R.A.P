import json
import queue
import time
import unittest

from hardware import BluetoothRobot, RobotError, SimulatedRobot


class FakeLink:
    """Stands in for the serial port: records writes and replays queued lines."""

    def __init__(self):
        self.written: list[bytes] = []
        self.incoming: queue.Queue = queue.Queue()
        self.fail_writes = False
        self.closed = False

    def write(self, data):
        if self.fail_writes:
            raise OSError("link lost")
        self.written.append(data)

    def readline(self):
        try:
            item = self.incoming.get(timeout=0.02)
        except queue.Empty:
            return b""
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def sensor_line(**overrides):
    message = {
        "type": "sensor_data",
        "device": "UGV_ESP32",
        "sensor": "DHT22",
        "simulated": False,
        "valid": True,
        "temperature_c": 29.5,
        "humidity_rh": 72.4,
        "timestamp_ms": 2500,
    }
    return (json.dumps(message | overrides) + "\n").encode()


def wait_until(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class TestSimulatedRobot(unittest.TestCase):

    def test_logs_commands_and_tracks_pose(self):
        robot = SimulatedRobot()
        robot.arm("inspect")
        robot.drive("forward", 800)
        robot.spray(500)

        self.assertEqual(
            robot.log,
            [("arm", "inspect"), ("drive", "forward", 800), ("spray", 500)],
        )
        self.assertEqual(robot.status()["arm_pose"], "inspect")

    def test_rejects_bad_commands(self):
        robot = SimulatedRobot()

        for bad in (
            lambda: robot.drive("jump"),
            lambda: robot.drive("forward", 10_000),
            lambda: robot.arm("flag"),
            lambda: robot.spray(0),
            lambda: robot.spray(5000),
        ):
            with self.assertRaises(RobotError):
                bad()
        self.assertEqual(robot.log, [])

    def test_fail_on_simulates_hardware_failure(self):
        robot = SimulatedRobot(fail_on={"inspect"})

        with self.assertRaises(RobotError):
            robot.arm("inspect")

    def test_has_no_sensor_reading_by_default(self):
        self.assertEqual(SimulatedRobot().sensors(), {})


class TestBluetoothRobot(unittest.TestCase):

    def make_robot(self, **kwargs):
        link = FakeLink()
        robot = BluetoothRobot("COM5", opener=lambda: link, **kwargs)
        self.addCleanup(robot.close)
        self.assertTrue(wait_until(lambda: robot.status()["connected"]))
        return robot, link

    def test_sends_firmware_commands(self):
        robot, link = self.make_robot()

        robot.drive("forward", 1000)
        robot.drive("back", 300)
        robot.drive("left", 500)
        robot.drive("right", 500)
        robot.stop()

        self.assertEqual(link.written, [b"F:1000\n", b"B:300\n", b"L:500\n", b"R:500\n", b"S\n"])

    def test_drive_stop_sends_stop(self):
        robot, link = self.make_robot()

        robot.drive("stop", 0)

        self.assertEqual(link.written, [b"S\n"])

    def test_untimed_move_is_refused(self):
        robot, link = self.make_robot()

        with self.assertRaises(RobotError):
            robot.drive("forward", 0)
        self.assertEqual(link.written, [])

    def test_arm_is_refused_until_firmware_supports_it(self):
        robot, link = self.make_robot()

        with self.assertRaises(RobotError):
            robot.arm("inspect")
        with self.assertRaises(RobotError):
            robot.spray(500)
        self.assertEqual(link.written, [])

    def test_arm_commands_when_enabled(self):
        robot, link = self.make_robot(has_arm=True)

        robot.arm("spray")
        robot.spray(500)

        self.assertEqual(link.written, [b"A:SPRAY\n", b"P:500\n"])

    def test_not_connected_raises(self):
        def refuse():
            raise OSError("no such port")

        robot = BluetoothRobot("COM9", opener=refuse)
        self.addCleanup(robot.close)

        with self.assertRaises(RobotError):
            robot.stop()
        self.assertFalse(robot.status()["connected"])

    def test_write_failure_raises_and_disconnects(self):
        robot, link = self.make_robot()
        link.fail_writes = True

        with self.assertRaises(RobotError):
            robot.stop()
        self.assertTrue(link.closed)

    def test_reads_sensor_data(self):
        robot, link = self.make_robot()

        link.incoming.put(sensor_line())

        self.assertTrue(wait_until(lambda: robot.sensors()))
        self.assertEqual(robot.sensors(), {"temperature_c": 29.5, "humidity_rh": 72.4})

    def test_ignores_invalid_simulated_and_garbled_lines(self):
        robot, link = self.make_robot()

        link.incoming.put(sensor_line(valid=False, temperature_c=None, humidity_rh=None))
        link.incoming.put(sensor_line(simulated=True))
        link.incoming.put(b"not json\n")
        link.incoming.put(b"[1, 2]\n")
        link.incoming.put(sensor_line(humidity_rh=55.0))

        self.assertTrue(wait_until(lambda: robot.sensors()))
        self.assertEqual(robot.sensors()["humidity_rh"], 55.0)

    def test_reconnects_after_read_failure(self):
        links = [FakeLink(), FakeLink()]
        opened = iter(links)
        robot = BluetoothRobot("COM5", opener=lambda: next(opened))
        self.addCleanup(robot.close)
        self.assertTrue(wait_until(lambda: robot.status()["connected"]))

        links[0].incoming.put(OSError("dropped"))

        self.assertTrue(wait_until(lambda: robot._link is links[1], timeout=4))


if __name__ == "__main__":
    unittest.main()
