from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from findbrokenlinks.config import Config
from findbrokenlinks.crawler import crawl
from findbrokenlinks.reporters import REGISTRY as REPORTER_REGISTRY  # noqa: F401 — side effects
from findbrokenlinks.reporters.base import get_reporter

_FORMATS = sorted(REPORTER_REGISTRY)


def _csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {v.strip() for v in value.split(",") if v.strip()}


# ---- numeric argparse type validators ----
# argparse converts the raw string via the `type` callable. A validator that
# raises argparse.ArgumentTypeError surfaces a clean "argument --foo: ..." error
# instead of a stack trace.


def _positive_int(value: str) -> int:
    """Strictly > 0."""
    try:
        i = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from e
    if i <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {i}")
    return i


def _positive_float(value: str) -> float:
    """Strictly > 0."""
    try:
        f = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from e
    if f <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {f}")
    return f


def _nonneg_int(value: str) -> int:
    """>= 0. Used where 0 has a documented meaning (usually 'unlimited')."""
    try:
        i = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from e
    if i < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {i}")
    return i


def _nonneg_float(value: str) -> float:
    """>= 0. Used where 0 has a documented meaning (usually 'unlimited')."""
    try:
        f = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}") from e
    if f < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {f}")
    return f


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="findbrokenlinks",
        description="Crawl a site and report broken or suspicious links.",
    )
    p.add_argument("url", help="seed URL to crawl")

    g = p.add_argument_group("scope")
    g.add_argument(
        "--mode",
        choices=("page", "internal", "internal+external"),
        default="internal+external",
    )
    g.add_argument(
        "--depth",
        type=_nonneg_int,
        default=0,
        help="max link depth, must be >= 0 (0 = unlimited)",
    )
    g.add_argument(
        "--max-pages",
        type=_nonneg_int,
        default=10_000,
        help="safety cap on total URLs enqueued (default: 10000, 0 = unlimited). "
        "Protects against unbounded URL spaces (session IDs, calendars, search facets).",
    )
    g.add_argument("--use-sitemap", action="store_true", help="seed queue from /sitemap.xml")

    g = p.add_argument_group("network")
    g.add_argument(
        "--rate-limit",
        type=_nonneg_float,
        default=5.0,
        dest="rate_limit_rps",
        help="requests per second, must be >= 0 (0 = unlimited)",
    )
    g.add_argument(
        "--concurrency",
        type=_positive_int,
        default=10,
        help="number of worker coroutines, must be >= 1",
    )
    g.add_argument(
        "--timeout",
        type=_positive_float,
        default=15.0,
        dest="timeout_s",
        help="per-request timeout in seconds, must be > 0",
    )
    g.add_argument(
        "--max-redirects",
        type=_nonneg_int,
        default=10,
        help="max redirect hops, must be >= 0 (0 = do not follow)",
    )
    g.add_argument(
        "--max-body-bytes",
        type=_positive_int,
        default=1_048_576,
        help="cap on text response body size (default: 1048576 = 1 MB), must be > 0. "
        "Non-text responses are never downloaded.",
    )
    g.add_argument(
        "--user-agent",
        default="findbrokenlinks/0.1 (+https://example.local)",
    )
    g.add_argument("--ignore-robots", action="store_true")

    g = p.add_argument_group("checks")
    g.add_argument("--enable-checks", default=None, help="comma-separated check codes")
    g.add_argument("--disable-checks", default=None, help="comma-separated check codes")
    g.add_argument(
        "--redirect-chain-threshold",
        type=_positive_int,
        default=3,
        help="flag chains with >= N hops, must be >= 1 (default: 3)",
    )
    g.add_argument("--patterns", type=Path, default=None, help="user soft-404 patterns YAML")
    g.add_argument("--no-soft404-probe", action="store_true")

    g = p.add_argument_group("output")
    g.add_argument(
        "--format",
        default="tsv",
        help=f"output format(s), comma-separated. Available: {','.join(_FORMATS)}",
    )
    g.add_argument(
        "--output", "-o", type=Path, default=None, help="output file (stdout if omitted)"
    )
    g.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for multi-format output (one file per format)",
    )

    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--log-file", type=Path, default=None)
    return p


def _setup_logging(verbose: bool, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _config_from_args(args: argparse.Namespace) -> Config:
    formats = [f.strip() for f in str(args.format).split(",") if f.strip()]
    for fmt in formats:
        if fmt not in REPORTER_REGISTRY:
            raise SystemExit(
                f"unknown format {fmt!r}; available: {', '.join(_FORMATS)}"
            )
    enabled = _csv_set(args.enable_checks) or None
    disabled = _csv_set(args.disable_checks)
    return Config(
        start_url=args.url,
        mode=args.mode,
        depth=args.depth,
        max_pages=args.max_pages,
        rate_limit_rps=args.rate_limit_rps,
        concurrency=args.concurrency,
        timeout_s=args.timeout_s,
        max_redirects=args.max_redirects,
        max_body_bytes=args.max_body_bytes,
        user_agent=args.user_agent,
        ignore_robots=args.ignore_robots,
        use_sitemap=args.use_sitemap,
        redirect_chain_threshold=args.redirect_chain_threshold,
        patterns_path=args.patterns,
        soft404_probe_enabled=not args.no_soft404_probe,
        enabled_checks=enabled,
        disabled_checks=disabled,
        formats=formats,
        output_path=args.output,
        output_dir=args.output_dir,
        verbose=args.verbose,
        log_file=args.log_file,
    )


def _write_batch_outputs(config: Config, findings) -> None:
    """Write outputs for batch-only or multi-format runs (called after crawl finishes)."""
    if len(config.formats) > 1:
        if not config.output_dir:
            raise SystemExit("multiple --format values require --output-dir")
        config.output_dir.mkdir(parents=True, exist_ok=True)
        for fmt in config.formats:
            reporter = get_reporter(fmt)
            data = reporter.render(findings)
            dst = config.output_dir / f"report.{reporter.file_ext}"
            dst.write_text(data, encoding="utf-8")
            print(f"wrote {dst}", file=sys.stderr)
        return

    reporter = get_reporter(config.formats[0])
    data = reporter.render(findings)
    if config.output_path:
        config.output_path.write_text(data, encoding="utf-8")
        print(f"wrote {config.output_path}", file=sys.stderr)
    else:
        sys.stdout.write(data)
        if not data.endswith("\n"):
            sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose, args.log_file)
    config = _config_from_args(args)

    # Streaming path: single streamable format → write incrementally as findings appear.
    if len(config.formats) == 1:
        reporter = get_reporter(config.formats[0])
        if reporter.streaming:
            return _run_streaming(config, reporter)

    findings = asyncio.run(crawl(config))
    _write_batch_outputs(config, findings)
    # Non-zero exit if there are error-level findings — useful for CI.
    return 1 if any(f.worst_severity == "error" for f in findings) else 0


def _run_streaming(config: Config, reporter) -> int:
    """Open output once, then emit each finding as it arrives from the crawl."""
    out = config.output_path.open("w", encoding="utf-8", newline="") \
        if config.output_path else sys.stdout
    has_error = [False]
    try:
        reporter.stream_start(out)

        def on_finding(f):
            reporter.stream_append(f, out)
            if f.worst_severity == "error":
                has_error[0] = True

        asyncio.run(crawl(config, on_finding=on_finding))
        reporter.stream_finish(out)
    finally:
        if out is not sys.stdout:
            out.close()
            print(f"wrote {config.output_path}", file=sys.stderr)
    return 1 if has_error[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
