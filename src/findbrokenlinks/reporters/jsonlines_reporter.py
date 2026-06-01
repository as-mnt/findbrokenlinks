from __future__ import annotations

import json
from typing import TextIO

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register
from findbrokenlinks.reporters.json_reporter import _finding_to_dict


@register
class JsonLinesReporter(Reporter):
    """Newline-delimited JSON — one finding per line, purpose-built for streaming."""

    name = "jsonl"
    file_ext = "jsonl"
    streaming = True

    def render(self, findings: list[Finding]) -> str:
        return "".join(self._line(f) for f in findings)

    def stream_append(self, finding: Finding, out: TextIO) -> None:
        out.write(self._line(finding))
        out.flush()

    @staticmethod
    def _line(finding: Finding) -> str:
        return json.dumps(_finding_to_dict(finding), ensure_ascii=False) + "\n"
