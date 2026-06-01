from __future__ import annotations

import csv
import io

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import ROW_FIELDS, Reporter, _row_for, register


@register
class CsvReporter(Reporter):
    name = "csv"
    file_ext = "csv"

    def render(self, findings: list[Finding]) -> str:
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for f in findings:
            writer.writerow(_row_for(f))
        return buf.getvalue()
