import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from hardware import HttpRobot, RobotError, SimulatedRobot


class FakeEsp32(BaseHTTPRequestHandler):
    """Minimal stand-in for the reference firmware's HTTP contract."""

    requests: list = []

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        FakeEsp32.requests.append((url.path, query))

        if url.path == "/drive" and query.get("cmd") in ("forward", "back", "left", "right", "stop"):
            self.reply(200, {"ok": True})
        elif url.path == "/arm" and query.get("pose") == "flag":
            self.reply(200, {"ok": False, "error": "servo jammed"})
        elif url.path == "/arm":
            self.reply(200, {"ok": True, "pose": query.get("pose")})
        elif url.path == "/status":
            self.reply(200, {"ok": True, "busy": False})
        else:
            self.reply(404, {"ok": False, "error": "not found"})

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TestSimulatedRobot(unittest.TestCase):

    def test_logs_commands_and_tracks_pose(self):
        robot = SimulatedRobot()
        robot.arm("inspect")
        robot.drive("forward", 800)

        self.assertEqual(robot.log, [("arm", "inspect"), ("drive", "forward", 800)])
        self.assertEqual(robot.status()["arm_pose"], "inspect")

    def test_rejects_bad_commands(self):
        robot = SimulatedRobot()

        with self.assertRaises(RobotError):
            robot.drive("jump")
        with self.assertRaises(RobotError):
            robot.drive("forward", 10_000)
        with self.assertRaises(RobotError):
            robot.arm("wave")
        self.assertEqual(robot.log, [])

    def test_fail_on_simulates_hardware_failure(self):
        robot = SimulatedRobot(fail_on={"inspect"})

        with self.assertRaises(RobotError):
            robot.arm("inspect")


class TestHttpRobot(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeEsp32)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeEsp32.requests.clear()
        self.robot = HttpRobot(drive_url=self.url, arm_url=self.url, timeout=2)

    def test_sends_contract_requests(self):
        self.robot.drive("left", 400)
        self.robot.arm("inspect")
        self.robot.stop()

        self.assertEqual(FakeEsp32.requests, [
            ("/drive", {"cmd": "left", "ms": "400"}),
            ("/arm", {"pose": "inspect"}),
            ("/drive", {"cmd": "stop", "ms": "0"}),
        ])

    def test_controller_refusal_raises(self):
        with self.assertRaises(RobotError) as ctx:
            self.robot.arm("flag")
        self.assertIn("servo jammed", str(ctx.exception))

    def test_invalid_command_is_not_sent(self):
        with self.assertRaises(RobotError):
            self.robot.drive("forward", 9999)
        self.assertEqual(FakeEsp32.requests, [])

    def test_status_reports_both_controllers(self):
        status = self.robot.status()

        self.assertTrue(status["connected"])
        self.assertFalse(status["simulated"])
        self.assertTrue(status["drive"]["connected"])

    def test_unreachable_controller(self):
        robot = HttpRobot(drive_url="http://127.0.0.1:1", timeout=0.5)

        with self.assertRaises(RobotError):
            robot.drive("forward", 100)
        status = robot.status()
        self.assertFalse(status["connected"])
        self.assertEqual(status["arm"]["error"], "not configured")

    def test_missing_controller(self):
        robot = HttpRobot(drive_url=self.url)

        with self.assertRaises(RobotError):
            robot.arm("home")


if __name__ == "__main__":
    unittest.main()
