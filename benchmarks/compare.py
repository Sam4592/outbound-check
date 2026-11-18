"""Compare a fresh benchmark run with the committed results.

Exits 1 if any scenario's pass/fail or set of failed rules changed, so a
change to the tool that silently alters a published finding is caught in CI.

    python benchmarks/compare.py benchmarks/kaymen99/results/direct/results.json results/direct/results.json
"""

import json
import sys


def summary(path):
    data = json.load(open(path, encoding="utf-8"))
    return {s["scenario"]: (s["passed"], tuple(s["failed_rules"])) for s in data["scenarios"]}


def main(expected_path, actual_path):
    expected, actual = summary(expected_path), summary(actual_path)
    problems = []
    for name in sorted(set(expected) | set(actual)):
        if expected.get(name) != actual.get(name):
            problems.append(f"{name}: expected {expected.get(name)}, got {actual.get(name)}")
    if problems:
        print("Benchmark results changed:")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print(f"{len(expected)} scenarios match {expected_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
