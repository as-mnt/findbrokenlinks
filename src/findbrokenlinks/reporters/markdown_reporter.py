from __future__ import annotations

from collections import defaultdict

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


@register
class MarkdownReporter(Reporter):
    name = "markdown"
    file_ext = "md"

    def render(self, findings: list[Finding]) -> str:
        sev_counts = {
            sev: sum(1 for f in findings if f.worst_severity == sev)
            for sev in ("error", "warning", "info")
        }
        lines = [
            "# findbrokenlinks report",
            "",
            f"Total: **{len(findings)}** "
            f"(errors: **{sev_counts['error']}**, "
            f"warnings: **{sev_counts['warning']}**, "
            f"info: **{sev_counts['info']}**)",
            "",
        ]
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            grouped[f.link.source_page].append(f)
        for src in sorted(grouped):
            items = grouped[src]
            lines.append(f"## [{src}]({src}) — {len(items)} issue(s)")
            lines.append("")
            lines.append("| severity | status | tag | link | codes | details |")
            lines.append("|---|---|---|---|---|---|")
            for f in items:
                status = "—" if f.fetch.status is None else str(f.fetch.status)
                codes = ", ".join(i.code for i in f.issues)
                msg = "; ".join(i.message for i in f.issues)
                link = f"[{_md_escape(f.link.url)}]({f.link.url})"
                lines.append(
                    f"| {f.worst_severity} | {status} | {f.link.tag} | {link} "
                    f"| {_md_escape(codes)} | {_md_escape(msg)} |"
                )
            lines.append("")
        return "\n".join(lines)
