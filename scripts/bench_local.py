#!/usr/bin/env python3
"""
Time and score the locally installed Ollama models on N questions of a locked set.

For each model it prints: total time, average time per question and score.
Only measured values are printed. Run it on the machine you want to measure
(for example the Mac M3, 16 GB reference machine) and paste the table into
the docs.

Needs the app's database (DATABASE_URL, the same one the app uses) and a
reachable Ollama (OLLAMA_BASE_URL, default http://localhost:11434).

Examples:
  python scripts/bench_local.py --set-id benchmark_v1 -n 10
  python scripts/bench_local.py --set-id benchmark_v1 -n 20 --models llama3.1:8b,qwen2.5:7b \\
      --machine "Mac M3, 16 GB"
  # Docker Compose database from the host:
  DATABASE_URL=postgresql+psycopg://benchmark:benchmark@localhost:5432/benchmark \\
      python scripts/bench_local.py --set-id benchmark_v1 -n 10

Exit codes: 0 done (individual model errors are shown in the table),
            1 cannot run (set not locked, no models, Ollama unreachable).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/bench_local.py` from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.adapters.ollama_adapter import discover_models, ollama_base_url  # noqa: E402
from src.benchmark.local_bench import BenchError, format_markdown, run_bench  # noqa: E402
from src.storage import db  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark installed Ollama models on N questions of a locked set.",
    )
    parser.add_argument("--set-id", required=True, help="id of a locked question set")
    parser.add_argument("-n", "--questions", type=int, default=10, help="how many questions to send (default 10)")
    parser.add_argument(
        "--models",
        help="comma-separated Ollama model names to test (default: every installed model)",
    )
    parser.add_argument("--base-url", help="Ollama address (default: OLLAMA_BASE_URL or http://localhost:11434)")
    parser.add_argument("--machine", help='label for the report header, e.g. "Mac M3, 16 GB"')
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="skip the warm-up request (the timed call then includes loading the model)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_url = (args.base_url or ollama_base_url()).rstrip("/")

    discovery = discover_models(base_url, timeout_s=5.0, use_cache=False)
    if not discovery.reachable:
        print(f"error: {discovery.error}", file=sys.stderr)
        return 1

    installed = [m.name for m in discovery.models]
    if args.models:
        wanted = [name.strip().removeprefix("ollama:") for name in args.models.split(",") if name.strip()]
        missing = [name for name in wanted if name not in installed]
        if missing:
            print(f"error: not installed in Ollama: {', '.join(missing)}", file=sys.stderr)
            print(f"installed: {', '.join(installed) or '(none)'}", file=sys.stderr)
            return 1
        names = wanted
    else:
        names = installed
    if not names:
        print("error: Ollama has no models installed (ollama pull <model>).", file=sys.stderr)
        return 1

    model_ids = [f"ollama:{name}" for name in names]
    session = db.SessionLocal()
    try:
        rows = run_bench(
            session,
            set_id=args.set_id,
            limit=args.questions,
            model_ids=model_ids,
            warmup=not args.no_warmup,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
    except BenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print()
    print(
        format_markdown(
            rows,
            set_id=args.set_id,
            questions=rows[0].questions if rows else args.questions,
            base_url=base_url,
            machine_label=args.machine,
            warmup=not args.no_warmup,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
