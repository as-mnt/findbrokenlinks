"""Group findings by ``final_url`` — one record per distinct broken target.

Real-world crawls of medium/large sites produce huge reports dominated by
site-wide footer/header links: one broken link in a template multiplies into
thousands of findings (one per page that includes the template). This reporter
collapses those into one record per ``final_url`` with the source-page list
preserved as a count plus a small sample.

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
          "status": …,
          "severity": …,
          "issue_codes": [...],
          "issue_messages": [...],
          "redirect_chain_length": …,
          "source_pages_sample": [...],     # first 5
          "link_urls_sample": [...],        # first 5
        },
        ...
      ]
    }

Groups are sorted by ``occurrences`` descending so the noisiest site-wide
templates surface first.
"""

from __future__ import annotations

import json
from collections import defaultdict

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register

_SAMPLE_SIZE = 5


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
        sample = group[0]
        return {
            "final_url": final_url,
            "occurrences": len(group),
            "distinct_source_pages": len(source_pages),
            "distinct_link_urls": len(link_urls),
            "status": sample.fetch.status,
            "error": sample.fetch.error,
            "content_type": sample.fetch.content_type,
            "severity": sample.worst_severity,
            "issue_codes": [i.code for i in sample.issues],
            "issue_messages": [i.message for i in sample.issues],
            "redirect_chain_length": max(0, len(sample.fetch.redirect_chain) - 1),
            "source_pages_sample": source_pages[:_SAMPLE_SIZE],
            "link_urls_sample": link_urls[:_SAMPLE_SIZE],
        }
