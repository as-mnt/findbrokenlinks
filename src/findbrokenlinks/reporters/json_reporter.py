from __future__ import annotations

import json

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


def _finding_to_dict(f: Finding) -> dict:
    return {
        "source_page": f.link.source_page,
        "link_url": f.link.url,
        "final_url": f.fetch.final_url,
        "anchor": f.link.anchor,
        "tag": f.link.tag,
        "status": f.fetch.status,
        "error": f.fetch.error,
        "content_type": f.fetch.content_type,
        "elapsed_ms": round(f.fetch.elapsed_ms, 2),
        "redirect_chain": f.fetch.redirect_chain,
        "severity": f.worst_severity,
        "issues": [
            {
                "code": i.code,
                "severity": i.severity,
                "message": i.message,
                "details": dict(i.details),
            }
            for i in f.issues
        ],
    }


@register
class JsonReporter(Reporter):
    name = "json"
    file_ext = "json"

    def render(self, findings: list[Finding]) -> str:
        payload = {
            "summary": {
                "total": len(findings),
                "by_severity": {
                    sev: sum(1 for f in findings if f.worst_severity == sev)
                    for sev in ("error", "warning", "info")
                },
            },
            "findings": [_finding_to_dict(f) for f in findings],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
