from __future__ import annotations

import json

from findbrokenlinks.checks.base import REGISTRY as CHECKS_REGISTRY
from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register

_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


@register
class SarifReporter(Reporter):
    """SARIF 2.1.0 — recognized by GitHub Code Scanning and many IDEs."""

    name = "sarif"
    file_ext = "sarif"

    def render(self, findings: list[Finding]) -> str:
        rules = [
            {
                "id": code,
                "name": cls.__name__,
                "shortDescription": {"text": code},
                "defaultConfiguration": {"level": _SARIF_LEVEL.get(cls.severity, "warning")},
            }
            for code, cls in CHECKS_REGISTRY.items()
        ]
        results = []
        for f in findings:
            for issue in f.issues:
                results.append(
                    {
                        "ruleId": issue.code,
                        "level": _SARIF_LEVEL.get(issue.severity, "warning"),
                        "message": {"text": issue.message},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": f.link.source_page}
                                },
                                "logicalLocations": [
                                    {"name": f.link.url, "kind": "url"}
                                ],
                            }
                        ],
                        "properties": {
                            "link_url": f.link.url,
                            "final_url": f.fetch.final_url,
                            "status": f.fetch.status,
                            "tag": f.link.tag,
                        },
                    }
                )
        sarif = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "findbrokenlinks",
                            "informationUri": "https://example.local/findbrokenlinks",
                            "rules": rules,
                        }
                    },
                    "results": results,
                }
            ],
        }
        return json.dumps(sarif, indent=2, ensure_ascii=False)
