"""Group findings by ``final_url`` — one record per distinct broken target.

Real-world crawls of medium/large sites produce huge reports dominated by
site-wide footer/header links: one broken link in a template multiplies into
thousands of findings (one per page that includes the template). This reporter
collapses those into one record per ``final_url`` with the source-page list
preserved as a count plus a small sample.

Aggregation rules (a single ``final_url`` can be reached from multiple
different request URLs with different statuses, redirect chains, and checks):

- ``severity`` is the **worst** observed severity across the group
- ``severity_distribution`` counts how many findings landed in each bucket
- ``statuses`` is a histogram of HTTP status codes (``"null"`` key for
  network failures)
- ``issue_codes`` / ``issue_messages`` are the **union** across the group,
  deduplicated and sorted
- ``max_redirect_chain_length`` is the longest chain seen
- ``errors`` and ``content_types`` are distinct non-null values

Output shape::

    {
      "summary": {
        "raw_findings": N,
        "unique_final_urls": M,
        "reduction_percent": X.X,
        "by_severity": {"error": …, "warning": …, "info": …}
      },
      "groups": [
        {
          "final_url": "…",
          "occurrences": K,
          "distinct_source_pages": K_pages,
          "distinct_link_urls": K_links,
          "severity": "error",
          "severity_distribution": {"error": E, "warning": W, "info": I},
          "statuses": {"404": 5, "502": 2, "null": 1},
          "issue_codes": [...],
          "issue_messages": [...],
          "max_redirect_chain_length": …,
          "errors": [...],
          "content_types": [...],
          "source_pages_sample": [...],
          "link_urls_sample": [...]
        },
        ...
      ]
    }

Groups are sorted by ``occurrences`` descending so the noisiest site-wide
templates surface first.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Sequence

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register

_SAMPLE_SIZE = 5
_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


def _worst_severity(severities: Sequence[str]) -> str:
    return max(severities, key=lambda s: _SEVERITY_RANK.get(s, -1)) if severities else "info"


@register
class GroupedJsonReporter(Reporter):
    name = "grouped-json"
    file_ext = "json"

    def render(self, findings: list[Finding]) -> str:
        groups: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            groups[f.fetch.final_url].append(f)

        records = [self._record(final_url, group) for final_url, group in groups.items()]
        records.sort(key=lambda r: -r["occurrences"])

        by_severity = {"error": 0, "warning": 0, "info": 0}
        for r in records:
            by_severity[r["severity"]] += 1

        total = len(findings)
        unique = len(records)
        payload = {
            "summary": {
                "raw_findings": total,
                "unique_final_urls": unique,
                "reduction_percent": (
                    round((1 - unique / total) * 100, 1) if total else 0.0
                ),
                "by_severity": by_severity,
            },
            "groups": records,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _record(final_url: str, group: list[Finding]) -> dict:
        source_pages = sorted({f.link.source_page for f in group})
        link_urls = sorted({f.link.url for f in group})

        severities: list[str] = [f.worst_severity for f in group]
        severity_distribution: Counter[str] = Counter(severities)
        statuses: Counter[str] = Counter()
        for f in group:
            # JSON object keys must be strings; preserve the None case as "null"
            # so a network-error group is still distinguishable from a real 0.
            statuses[str(f.fetch.status) if f.fetch.status is not None else "null"] += 1

        issue_codes: set[str] = set()
        issue_messages: set[str] = set()
        for f in group:
            for issue in f.issues:
                issue_codes.add(issue.code)
                issue_messages.add(issue.message)

        max_chain = max(
            (max(0, len(f.fetch.redirect_chain) - 1) for f in group),
            default=0,
        )
        errors = sorted({f.fetch.error for f in group if f.fetch.error})
        content_types = sorted({f.fetch.content_type for f in group if f.fetch.content_type})

        return {
            "final_url": final_url,
            "occurrences": len(group),
            "distinct_source_pages": len(source_pages),
            "distinct_link_urls": len(link_urls),
            "severity": _worst_severity(severities),
            "severity_distribution": {
                # stable order matching summary's by_severity for easy reading
                sev: severity_distribution.get(sev, 0)
                for sev in ("error", "warning", "info")
            },
            "statuses": dict(sorted(statuses.items())),
            "issue_codes": sorted(issue_codes),
            "issue_messages": sorted(issue_messages),
            "max_redirect_chain_length": max_chain,
            "errors": errors,
            "content_types": content_types,
            "source_pages_sample": source_pages[:_SAMPLE_SIZE],
            "link_urls_sample": link_urls[:_SAMPLE_SIZE],
        }
