"""Rendering the scorecard a person reads from the document a machine wrote.

The Markdown is a projection of the JSON and never a second computation. If a
number appears here it was read out of the artifact, which is why the two cannot
drift: there is no arithmetic in this module beyond formatting a rate that is
already in the file.

Everything printed carries the thing it is evidence of. A scorecard that states
its denominators, names its fixture, and says in the first line that it measures
control-plane behaviour is one a reader can trust; the same numbers with the
labels stripped are how "100% citation validity on a five-passage fixture" ends up
quoted as a retrieval result.

Usable on its own::

    python -m agentic_rag.evals.render --results reports/evals/latest.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agentic_rag.evals.results import write_text

UNDEFINED = "n/a"
"""Printed where a rate has no denominator. Never 0% and never 100%."""


def _rate(metric: Mapping[str, Any]) -> str:
    """Return a metric's value as a percentage with its arithmetic beside it."""
    numerator = metric["numerator"]
    denominator = metric["denominator"]
    if metric.get("value") is None:
        return f"{UNDEFINED} (0 denominator)"
    return f"{float(metric['value']) * 100:.1f}% ({numerator}/{denominator})"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    """Return a Markdown table, or a note where there is nothing to show."""
    if not rows:
        return ["_No rows._", ""]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    lines.append("")
    return lines


def _metric_rows(metrics: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    """Return one row per metric: what it measures, over what, and the result."""
    return [
        [
            f"`{metric['id']}`",
            metric["description"],
            metric["denominator_meaning"],
            _rate(metric),
        ]
        for metric in metrics
    ]


def _header(payload: Mapping[str, Any]) -> list[str]:
    """Return the title, the disclaimer, and the run's provenance."""
    run = payload["run"]
    dataset = payload["dataset"]
    zero_cost = (
        "$0 billed"
        if _free_path_proven(payload)
        else "cost not established from this run's records"
    )
    return [
        "# Agentic research loop — fixture scorecard",
        "",
        f"> **Evidence class: {payload['evidence_class']}.** {payload['disclaimer']}",
        "",
        *_table(
            ["Field", "Value"],
            [
                ["Dataset", f"`{dataset['path']}`"],
                ["Dataset digest", f"`{dataset['sha256']}`"],
                ["Cases", str(dataset["case_count"])],
                ["Retrieval backend", f"`{run['backend']}` over {run['corpus_size']} passages"],
                ["Package version", run["package_version"]],
                ["Command", f"`{run['command']}`" if run["command"] else "—"],
                ["Network", "not used"],
                ["Cost", zero_cost],
                ["Generated at", str(run["generated_at"])],
                ["Results digest", f"`{payload['results_digest']}`"],
            ],
        ),
        f"Volatile fields, excluded from the digest: "
        f"{', '.join(f'`{field}`' for field in payload['volatile_fields'])}.",
        "",
    ]


def _free_path_proven(payload: Mapping[str, Any]) -> bool:
    """Return whether the records prove every step was served by the bound fixture.

    The zero-cost line is printed only when this holds. A run that cannot show
    which backend served it has not earned the claim, however free the code path
    looks from the outside.
    """
    for metric in payload["metrics"]:
        if metric["id"] == "free_path_share":
            return bool(metric.get("value") == 1.0 and metric["denominator"] > 0)
    return False


def _invariants(payload: Mapping[str, Any]) -> list[str]:
    """Return the hard-gate section, listing every violation in full."""
    outcomes = payload["invariants"]
    rows = [
        [
            f"`{outcome['id']}`",
            outcome["description"],
            str(outcome["cases_checked"]),
            "held"
            if outcome["cases_violating"] == 0
            else f"**{outcome['cases_violating']} failed**",
        ]
        for outcome in outcomes
    ]
    lines = [
        "## Hard invariants",
        "",
        "Properties every run must have, whatever the dataset expects. A violation "
        "fails the evaluation and exits nonzero.",
        "",
        *_table(["Invariant", "Property", "Runs checked", "Result"], rows),
    ]
    failures = [outcome for outcome in outcomes if outcome["cases_violating"]]
    if failures:
        lines.extend(["### Violations", ""])
        for outcome in failures:
            lines.append(f"**`{outcome['id']}`**")
            lines.append("")
            lines.extend(f"- {message}" for message in outcome["violations"])
            lines.append("")
    return lines


def _determinism(payload: Mapping[str, Any]) -> list[str]:
    """Return the repeat-run section."""
    determinism = payload["determinism"]
    repeats = determinism["repeats"]
    unique = len(set(determinism["digests"]))
    if repeats < 2:
        verdict = "unproven — a single pass cannot demonstrate stability"
    elif determinism["stable"]:
        verdict = f"stable across {repeats} passes"
    else:
        verdict = f"**unstable**: {unique} distinct digests across {repeats} passes"
    return [
        "## Determinism",
        "",
        f"{verdict}. The digest covers the per-case records only, so it is unaffected by "
        "when or where the evaluation ran.",
        "",
        *_table(
            ["Pass", "Digest of case records"],
            [
                [str(index), f"`{digest}`"]
                for index, digest in enumerate(determinism["digests"], start=1)
            ],
        ),
    ]


def _metrics(payload: Mapping[str, Any]) -> list[str]:
    """Return the descriptive-metrics section and the per-slice breakdown."""
    lines = [
        "## Descriptive metrics",
        "",
        "Agreement between the curated expectations and what the loop did. These do not "
        "fail the run: a disagreement can mean the loop regressed or that the expectation "
        "was wrong, and only a reader can tell which.",
        "",
        *_table(
            ["Metric", "Measures", "Denominator", "Result"],
            _metric_rows(payload["metrics"]),
        ),
        "## By behaviour slice",
        "",
    ]
    for category, metrics in payload["metrics_by_category"].items():
        interesting = [
            metric
            for metric in metrics
            if metric["id"]
            in {
                "terminal_status_agreement",
                "stop_reason_agreement",
                "expected_source_match",
                "repeated_evidence_dedup",
                "plan_expansion_agreement",
                "all_declared_expectations_met",
            }
        ]
        lines.append(f"### `{category}`")
        lines.append("")
        lines.extend(
            _table(
                ["Metric", "Result"],
                [[f"`{metric['id']}`", _rate(metric)] for metric in interesting],
            )
        )
    return lines


def _distribution(payload: Mapping[str, Any]) -> list[str]:
    """Return the steps-distribution section."""
    distribution = payload["steps_distribution"]
    total = sum(distribution.values()) or 1
    rows = [
        [steps, str(count), f"{count / total * 100:.1f}%"]
        for steps, count in distribution.items()
    ]
    return [
        "## Steps spent",
        "",
        "How many retrieval steps each run spent before it stopped.",
        "",
        *_table(["Steps", "Runs", "Share"], rows),
    ]


def _baseline(payload: Mapping[str, Any]) -> list[str]:
    """Return the single-pass reference section, with its limits stated first."""
    cases = payload["cases"]
    with_baseline = [case for case in cases if case.get("baseline")]
    more = sum(
        1
        for case in with_baseline
        if len(set(case["observed"]["evidence_ids"])) > case["baseline"]["evidence_count"]
    )
    same = sum(
        1
        for case in with_baseline
        if len(set(case["observed"]["evidence_ids"])) == case["baseline"]["evidence_count"]
    )
    fewer = len(with_baseline) - more - same
    return [
        "## Single-pass reference",
        "",
        "One retrieval call for the whole question, same fixture, same `top_k`, no plan and "
        "no critique. It is a **control-flow** reference: it produces no answer, so it "
        "supports no statement about answer quality, and both sides retrieve by lexical "
        "overlap over the same five passages.",
        "",
        *_table(
            ["Comparison", "Cases"],
            [
                ["Loop gathered more distinct passages", str(more)],
                ["Loop gathered the same number", str(same)],
                ["Loop gathered fewer", str(fewer)],
            ],
        ),
    ]


def _cases(payload: Mapping[str, Any]) -> list[str]:
    """Return the per-case table."""
    rows = []
    for case in payload["cases"]:
        observed = case["observed"]
        matched = "yes" if not _mismatches(case) else "**no**"
        rows.append(
            [
                f"`{case['id']}`",
                case["category"],
                f"{observed['status']} / {observed['stop_reason']}",
                f"{observed['steps_used']}/{case['max_steps']}",
                str(len(observed["citation_markers"])),
                matched,
                "clean" if not case["invariant_violations"] else "**violated**",
            ]
        )
    return [
        "## Cases",
        "",
        *_table(
            [
                "Case",
                "Slice",
                "Status / reason",
                "Steps",
                "Citations",
                "Met expectations",
                "Invariants",
            ],
            rows,
        ),
    ]


def _mismatches(case: Mapping[str, Any]) -> list[str]:
    """Return the names of the declared constraints this case did not meet."""
    return [name for name, met in case["matches"].items() if met is False]


def _limits() -> list[str]:
    """Return the section that says what the artifact cannot support."""
    return [
        "## What this scorecard does not measure",
        "",
        "- **Retrieval quality.** The backend is a lexical-overlap fixture over five committed "
        "passages. It is a stand-in for a retrieval service, not a small one.",
        "- **Answer quality or faithfulness.** The synthesiser selects and marks retrieved "
        "passages; it writes no prose, so there is nothing to be unfaithful to and nothing "
        "here measures whether an answer is good.",
        "- **Latency or throughput.** No timing is recorded, deliberately.",
        "- **Production readiness.** Every run is in-process against a fixture.",
        "- **Any comparison with another system.** The only reference here is the single "
        "retrieval pass over the same fixture.",
        "",
        "What it does measure: whether the loop stops for the reason its own rules imply, "
        "stays inside its budget, cites only what it retrieved, records a complete trace, "
        "deduplicates repeated evidence, refuses when it has nothing, and produces the same "
        "output twice.",
        "",
    ]


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Return the Markdown scorecard for a results document.

    Args:
        payload: A parsed results JSON document.

    Returns:
        The scorecard text, newline-terminated.
    """
    lines: list[str] = []
    lines.extend(_header(payload))
    lines.extend(_invariants(payload))
    lines.extend(_determinism(payload))
    lines.extend(_metrics(payload))
    lines.extend(_distribution(payload))
    lines.extend(_baseline(payload))
    lines.extend(_cases(payload))
    lines.extend(_limits())
    return "\n".join(lines).rstrip("\n") + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the standalone renderer.

    Returns:
        A parser reading a results file and writing Markdown.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agentic_rag.evals.render",
        description="Render the Markdown scorecard from an evaluation results file.",
    )
    parser.add_argument(
        "--results",
        type=Path,
        required=True,
        help="Results JSON written by python -m agentic_rag.evals.run.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Where to write the Markdown. Omitted, it goes to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Render a results file to Markdown.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        Zero. Rendering has no gate to fail; the run that produced the file did.
    """
    arguments = build_parser().parse_args(argv)
    payload = json.loads(Path(arguments.results).read_text(encoding="utf-8"))
    markdown = render_markdown(payload)
    if arguments.out is None:
        print(markdown, end="")
    else:
        write_text(Path(arguments.out), markdown)
        print(f"wrote {Path(arguments.out).as_posix()}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the module CLI
    raise SystemExit(main())
