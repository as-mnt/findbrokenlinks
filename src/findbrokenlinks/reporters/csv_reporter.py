from __future__ import annotations

import csv
import io
from typing import TextIO

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import ROW_FIELDS, Reporter, _row_for, register


@register
class CsvReporter(Reporter):
    name = "csv"
    file_ext = "csv"
    streaming = True

    def render(self, findings: list[Finding]) -> str:
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for f in findings:
            writer.writerow(_row_for(f))
        return buf.getvalue()

    def stream_start(self, out: TextIO) -> None:
        writer = csv.DictWriter(out, fieldnames=ROW_FIELDS)
        writer.writeheader()
        out.flush()

    def stream_append(self, finding: Finding, out: TextIO) -> None:
        writer = csv.DictWriter(out, fieldnames=ROW_FIELDS)
        writer.writerow(_row_for(finding))
        out.flush()
