from __future__ import annotations

import csv
import io
from typing import TextIO

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import ROW_FIELDS, Reporter, _row_for, register


def _sanitized(finding: Finding) -> dict[str, object]:
    row = _row_for(finding)
    for k, v in row.items():
        if isinstance(v, str):
            row[k] = v.replace("\t", " ").replace("\n", " ")
    return row


@register
class TsvReporter(Reporter):
    name = "tsv"
    file_ext = "tsv"
    streaming = True

    def render(self, findings: list[Finding]) -> str:
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=ROW_FIELDS, delimiter="\t")
        writer.writeheader()
        for f in findings:
            writer.writerow(_sanitized(f))
        return buf.getvalue()

    def stream_start(self, out: TextIO) -> None:
        writer = csv.DictWriter(out, fieldnames=ROW_FIELDS, delimiter="\t")
        writer.writeheader()
        out.flush()

    def stream_append(self, finding: Finding, out: TextIO) -> None:
        writer = csv.DictWriter(out, fieldnames=ROW_FIELDS, delimiter="\t")
        writer.writerow(_sanitized(finding))
        out.flush()
