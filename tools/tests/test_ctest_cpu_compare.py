import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctest_cpu_compare

BURN = "import sys, time\nend = time.process_time() + float(sys.argv[1])\nwhile time.process_time() < end:\n    pass\n"
EXIT = "import sys\nsys.exit(int(sys.argv[1]))\n"
SHOW = "import os, sys\nopen(sys.argv[1], 'a').write(os.environ['FIXTURE_VALUE'] + '|' + os.getcwd() + '\\n')\n"


@unittest.skipIf(sys.platform == "win32", "the resource module is not available on Windows")
class CompareTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.baseline, self.candidate = self.root / "a", self.root / "b"
        for build, seconds in ((self.baseline, "0.20"), (self.candidate, "0.05")):
            build.mkdir()
            (build / "burn.py").write_text(BURN, encoding="utf-8")
            (build / "exit.py").write_text(EXIT, encoding="utf-8")
            (build / "show.py").write_text(SHOW, encoding="utf-8")
            (build / "seconds.txt").write_text(seconds, encoding="utf-8")

    def entry(self, name, script, *arguments, environment=None, directory=None):
        properties = []
        if environment:
            properties.append({"name": "ENVIRONMENT", "value": environment})
        if directory:
            properties.append({"name": "WORKING_DIRECTORY", "value": directory})
        return {"name": name, "command": [sys.executable, str(self.baseline / script), *arguments], "properties": properties}

    def listing(self, *tests):
        file = self.root / "tests.json"
        file.write_text(json.dumps({"tests": list(tests)}), encoding="utf-8")
        return file

    def run_tool(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors:
            code = ctest_cpu_compare.main(["--baseline", str(self.baseline), "--candidate", str(self.candidate), *arguments])
        return code, output.getvalue(), errors.getvalue()

    def test_candidate_commands_run_from_the_candidate_directory_and_cpu_time_is_compared(self):
        burn = self.root / "burn.py"
        burn.write_text("import pathlib, sys, time\nend = time.process_time() + float((pathlib.Path(sys.argv[1]) / 'seconds.txt').read_text())\n"
                        "while time.process_time() < end:\n    pass\n", encoding="utf-8")
        listing = self.listing({"name": "fixture_burn", "command": [sys.executable, str(burn), str(self.baseline)], "properties": []},
                               self.entry("other_burn", "burn.py", "0.01"))
        result = self.root / "result.json"
        code, output, _ = self.run_tool("--tests", str(listing), "--regex", "^fixture_", "--rounds", "1", "--json", str(result))
        self.assertEqual(code, 0)
        data = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual((data["tests"], data["runs_per_build"], data["excluded"]), (1, 2, {}))
        self.assertEqual(list(data["per_test_median_cpu_seconds"]), ["fixture_burn"])
        self.assertGreater(data["median_cpu_seconds"]["baseline"], 0.18)
        self.assertLess(data["median_cpu_seconds"]["candidate"], 0.15)
        self.assertLess(data["change_percent"], -20)
        self.assertIn("not a frame rate", output)

    def test_environment_and_working_directory_follow_the_build(self):
        log = self.root / "seen.txt"
        listing = self.listing(self.entry("fixture_show", "show.py", str(log), environment=[f"FIXTURE_VALUE={self.baseline}/libs"],
                                         directory=str(self.baseline)))
        code, _, _ = self.run_tool("--tests", str(listing), "--regex", "fixture", "--rounds", "1")
        self.assertEqual(code, 0)
        seen = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(seen, [f"{self.baseline}/libs|{self.baseline}", f"{self.candidate}/libs|{self.candidate}",
                                f"{self.candidate}/libs|{self.candidate}", f"{self.baseline}/libs|{self.baseline}"])

    def test_failed_and_skipped_tests_are_excluded_and_named(self):
        listing = self.listing(self.entry("fixture_ok", "exit.py", "0"), self.entry("fixture_skip", "exit.py", "77"),
                               self.entry("fixture_fail", "exit.py", "3"))
        result = self.root / "result.json"
        code, output, _ = self.run_tool("--tests", str(listing), "--regex", "fixture", "--rounds", "2", "--json", str(result))
        self.assertEqual(code, 0)
        data = json.loads(result.read_text(encoding="utf-8"))
        self.assertEqual(data["excluded"], {"fixture_fail": "exit code 3", "fixture_skip": "skipped"})
        self.assertEqual((data["tests"], data["runs_per_build"]), (1, 4))
        self.assertIn("excluded fixture_skip: skipped", output)

    def test_no_match_and_no_passing_test_are_errors(self):
        listing = self.listing(self.entry("fixture_fail", "exit.py", "3"))
        code, _, errors = self.run_tool("--tests", str(listing), "--regex", "absent")
        self.assertEqual(code, 2)
        self.assertIn("no registered test matches", errors)
        code, _, errors = self.run_tool("--tests", str(listing), "--regex", "fixture", "--rounds", "1")
        self.assertEqual(code, 1)
        self.assertIn("no selected test passed in both builds", errors)

    def test_selection_keeps_only_tests_with_a_command(self):
        listing = {"tests": [{"name": "fixture_without_command"}, self.entry("fixture_ok", "exit.py", "0")]}
        chosen = ctest_cpu_compare.select(listing, self.baseline, re.compile("fixture"))
        self.assertEqual([test["name"] for test in chosen], ["fixture_ok"])


if __name__ == "__main__":
    unittest.main()
