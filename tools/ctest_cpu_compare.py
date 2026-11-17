#!/usr/bin/env python3
"""Compare the CPU time of registered tests between two build directories.

Both directories are builds of the same test set, for example main and a change,
or one tree configured with two values of a build option. The tests selected by
--regex are run from each directory in alternating rounds (baseline, candidate,
candidate, baseline), each with the environment CTest gives it, and the user plus
system CPU time of every test process and its children is summed per round.

The result is the CPU time of those tests on this machine. A test that runs on a
software Vulkan driver spends part of that time in the driver, the same in both
builds. It is not a frame rate and says nothing about a title.
"""
import argparse
import json
import os
import re
import resource
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ORDER = ("baseline", "candidate", "candidate", "baseline")
SKIPPED = 77


def registered(build):
    listing = subprocess.run(["ctest", "--test-dir", str(build), "--show-only=json-v1"], capture_output=True, text=True, check=True)
    return json.loads(listing.stdout)


def select(listing, build, pattern):
    chosen = []
    for test in listing.get("tests", []):
        command = test.get("command")
        if not command or not pattern.search(test["name"]):
            continue
        properties = {entry["name"]: entry["value"] for entry in test.get("properties", [])}
        chosen.append({"name": test["name"], "command": command, "environment": properties.get("ENVIRONMENT", []),
                       "directory": properties.get("WORKING_DIRECTORY"), "build": str(build)})
    return chosen


def rebased(text, source, target):
    return text.replace(source.rstrip("/\\"), target.rstrip("/\\")) if text else text


def measure(test, build, scratch, timeout):
    environment = dict(os.environ)
    for entry in test["environment"]:
        name, _, value = entry.partition("=")
        environment[name] = rebased(value, test["build"], str(build))
    command = [rebased(part, test["build"], str(build)) for part in test["command"]]
    directory = rebased(test["directory"], test["build"], str(build)) or scratch
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        code = subprocess.run(command, cwd=directory, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout).returncode
    except (OSError, subprocess.TimeoutExpired):
        code = None
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return code, (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)


def compare(tests, baseline, candidate, rounds, timeout):
    builds = {"baseline": baseline, "candidate": candidate}
    samples = {test["name"]: {"baseline": [], "candidate": []} for test in tests}
    excluded = {}
    with tempfile.TemporaryDirectory() as scratch:
        for _ in range(rounds):
            for arm in ORDER:
                for test in tests:
                    if test["name"] in excluded:
                        continue
                    code, seconds = measure(test, builds[arm], scratch, timeout)
                    if code != 0:
                        excluded[test["name"]] = "skipped" if code == SKIPPED else "timed out or did not start" if code is None else f"exit code {code}"
                        continue
                    samples[test["name"]][arm].append(seconds)
    kept = [name for name in samples if name not in excluded]
    runs = 2 * rounds
    totals = {arm: [sum(samples[name][arm][index] for name in kept) for index in range(runs)] for arm in builds} if kept else {arm: [] for arm in builds}
    result = {"tests": len(kept), "runs_per_build": runs if kept else 0, "excluded": dict(sorted(excluded.items())),
              "cpu_seconds": {arm: [round(value, 4) for value in values] for arm, values in totals.items()}}
    if kept:
        medians = {arm: statistics.median(values) for arm, values in totals.items()}
        result["median_cpu_seconds"] = {arm: round(value, 4) for arm, value in medians.items()}
        result["change_percent"] = round(100 * (medians["candidate"] / medians["baseline"] - 1), 2) if medians["baseline"] else None
        result["spread_percent"] = {arm: round(100 * (max(values) - min(values)) / medians[arm], 2) if medians[arm] else None for arm, values in totals.items()}
        result["per_test_median_cpu_seconds"] = {name: {arm: round(statistics.median(samples[name][arm]), 4) for arm in builds} for name in kept}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--baseline", type=Path, required=True, help="build directory of the reference")
    parser.add_argument("--candidate", type=Path, required=True, help="build directory of the change, with the same tests built")
    parser.add_argument("--regex", "-R", required=True, help="regular expression selecting test names, as ctest -R")
    parser.add_argument("--rounds", type=int, default=3, help="rounds of baseline, candidate, candidate, baseline (default 3)")
    parser.add_argument("--timeout", type=float, default=300, help="seconds one test may run (default 300)")
    parser.add_argument("--tests", type=Path, help="read the test list from this ctest --show-only=json-v1 file instead of running ctest in the baseline directory")
    parser.add_argument("--json", type=Path, help="write the result to this file")
    arguments = parser.parse_args(argv)
    if arguments.rounds < 1:
        parser.error("--rounds must be at least 1")
    baseline, candidate = arguments.baseline.resolve(), arguments.candidate.resolve()
    listing = json.loads(arguments.tests.read_text(encoding="utf-8")) if arguments.tests else registered(baseline)
    tests = select(listing, baseline, re.compile(arguments.regex))
    if not tests:
        print("no registered test matches the expression", file=sys.stderr)
        return 2
    result = compare(tests, baseline, candidate, arguments.rounds, arguments.timeout)
    if arguments.json:
        arguments.json.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for name, reason in result["excluded"].items():
        print(f"excluded {name}: {reason}")
    if not result["tests"]:
        print("no selected test passed in both builds", file=sys.stderr)
        return 1
    medians, spread = result["median_cpu_seconds"], result["spread_percent"]
    print(f"{result['tests']} tests, {result['runs_per_build']} runs per build")
    print(f"baseline  median {medians['baseline']:.3f} s CPU, spread {spread['baseline']} %")
    print(f"candidate median {medians['candidate']:.3f} s CPU, spread {spread['candidate']} %")
    print(f"change {result['change_percent']:+.2f} % CPU time of these tests on this machine; not a frame rate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
