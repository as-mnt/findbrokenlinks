from __future__ import annotations

from collections import defaultdict
from html import escape

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register

_SEV_COLOR = {"error": "#c62828", "warning": "#ef6c00", "info": "#1565c0"}


def _section(source: str, items: list[Finding]) -> str:
    rows = []
    for f in items:
        sev = f.worst_severity
        color = _SEV_COLOR.get(sev, "#333")
        codes = ", ".join(i.code for i in f.issues)
        msg = escape("; ".join(i.message for i in f.issues))
        status = "—" if f.fetch.status is None else str(f.fetch.status)
        final = f.fetch.final_url
        rows.append(
            f"<tr>"
            f"<td style='color:{color};font-weight:600'>{escape(sev)}</td>"
            f"<td>{escape(status)}</td>"
            f"<td>{escape(f.link.tag)}</td>"
            f"<td><a href='{escape(f.link.url, quote=True)}' target='_blank' rel='noreferrer'>"
            f"{escape(f.link.url)}</a></td>"
            f"<td><a href='{escape(final, quote=True)}' target='_blank' rel='noreferrer'>"
            f"{escape(final)}</a></td>"
            f"<td>{escape(codes)}</td>"
            f"<td>{msg}</td>"
            f"</tr>"
        )
    rows_html = "\n".join(rows)
    return (
        f"<section>"
        f"<h2><a href='{escape(source, quote=True)}' target='_blank' rel='noreferrer'>"
        f"{escape(source)}</a> "
        f"<small>({len(items)} issue(s))</small></h2>"
        f"<table><thead><tr>"
        f"<th>severity</th><th>status</th><th>tag</th>"
        f"<th>link</th><th>final url</th><th>codes</th><th>details</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
        f"</section>"
    )


@register
class HtmlReporter(Reporter):
    name = "html"
    file_ext = "html"

    def render(self, findings: list[Finding]) -> str:
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            grouped[f.link.source_page].append(f)

        sev_counts = {
            sev: sum(1 for f in findings if f.worst_severity == sev)
            for sev in ("error", "warning", "info")
        }
        summary = (
            f"<p>Total findings: <b>{len(findings)}</b> "
            f"&middot; errors: <b>{sev_counts['error']}</b> "
            f"&middot; warnings: <b>{sev_counts['warning']}</b> "
            f"&middot; info: <b>{sev_counts['info']}</b></p>"
        )

        body = "\n".join(_section(src, items) for src, items in sorted(grouped.items()))
        return (
            "<!doctype html><html><head>"
            "<meta charset='utf-8'>"
            "<title>findbrokenlinks report</title>"
            "<style>"
            "body{font:14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#222}"
            "h1{margin:0 0 12px}h2{margin:24px 0 8px;font-size:16px}"
            "table{border-collapse:collapse;width:100%;font-size:13px}"
            "th,td{border:1px solid #ddd;padding:6px 8px;vertical-align:top;text-align:left}"
            "th{background:#f5f5f5}"
            "section{margin-bottom:24px}"
            "a{color:#1565c0;text-decoration:none}a:hover{text-decoration:underline}"
            "</style></head><body>"
            "<h1>findbrokenlinks report</h1>"
            f"{summary}{body}"
            "</body></html>"
        )
