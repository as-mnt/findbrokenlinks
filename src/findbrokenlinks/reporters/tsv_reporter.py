from __future__ import annotations

import csv
import io

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import ROW_FIELDS, Reporter, _row_for, register


@register
class TsvReporter(Reporter):
    name = "tsv"
    file_ext = "tsv"

    def render(self, findings: list[Finding]) -> str:
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=ROW_FIELDS, delimiter="\t")
        writer.writeheader()
        for f in findings:
            row = _row_for(f)
            # Sanitize tabs/newlines that would corrupt the format.
            for k, v in row.items():
                if isinstance(v, str):
                    row[k] = v.replace("\t", " ").replace("\n", " ")
            writer.writerow(row)
        return buf.getvalue()
