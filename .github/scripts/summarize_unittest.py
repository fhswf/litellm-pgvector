#!/usr/bin/env python3
"""Turn verbose unittest output into a compact Markdown report."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


RESULT_LINE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<case>.+?)\)\s+\.\.\.\s+"
    r"(?P<result>ok|FAIL|ERROR|skipped(?:\s+.+)?|"
    r"expected failure|unexpected success)$"
)


def summarize(log: str) -> str:
    counts: Counter[str] = Counter()
    failures: list[tuple[str, str]] = []

    for line in log.splitlines():
        match = RESULT_LINE.match(line.strip())
        if not match:
            continue

        name = f"{match['name']} ({match['case']})"
        safe_name = (
            name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("`", "&#96;")
            .replace("@", "&#64;")
        )
        result = match["result"]
        if result == "ok":
            counts["passed"] += 1
        elif result == "FAIL":
            counts["failed"] += 1
            failures.append((safe_name, "failed"))
        elif result == "ERROR":
            counts["errors"] += 1
            failures.append((safe_name, "error"))
        elif result.startswith("skipped"):
            counts["skipped"] += 1
        elif result == "expected failure":
            counts["expected failures"] += 1
        else:  # An unexpected success makes unittest exit with a failure.
            counts["failed"] += 1
            failures.append((safe_name, "unexpected success"))

    total = sum(counts.values())
    if total == 0 and not re.search(r"Ran 0 tests?\b", log):
        return (
            "### Integration tests\n\n"
            "⚠️ No unittest result lines were found. See the test job logs for details."
        )

    report = [
        "### Integration tests",
        "",
        "| Passed | Failed | Errors | Skipped | Expected failures |",
        "| ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {counts['passed']} | {counts['failed']} | {counts['errors']} | "
            f"{counts['skipped']} | {counts['expected failures']} |"
        ),
    ]

    if failures:
        report.extend(["", "**Failed tests**"])
        report.extend(f"- `{name}` — {result}" for name, result in failures)

    return "\n".join(report)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: summarize_unittest.py INPUT_LOG OUTPUT_MARKDOWN")

    source, destination = map(Path, sys.argv[1:])
    destination.write_text(summarize(source.read_text(errors="replace")) + "\n")


if __name__ == "__main__":
    main()
