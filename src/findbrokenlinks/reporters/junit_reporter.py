from __future__ import annotations

from collections import defaultdict
from xml.etree.ElementTree import Element, SubElement, tostring

from findbrokenlinks.models import Finding
from findbrokenlinks.reporters.base import Reporter, register


@register
class JunitReporter(Reporter):
    """Emit a JUnit XML where each broken link is a failed testcase.

    Suites are grouped by source page so CI dashboards show issues per page.
    """

    name = "junit"
    file_ext = "xml"

    def render(self, findings: list[Finding]) -> str:
        suites = Element("testsuites")
        grouped: dict[str, list[Finding]] = defaultdict(list)
        for f in findings:
            grouped[f.link.source_page].append(f)

        total = len(findings)
        suites.set("name", "findbrokenlinks")
        suites.set("tests", str(total))
        suites.set("failures", str(total))

        for src, items in sorted(grouped.items()):
            suite = SubElement(
                suites,
                "testsuite",
                {
                    "name": src,
                    "tests": str(len(items)),
                    "failures": str(len(items)),
                },
            )
            for f in items:
                case = SubElement(
                    suite,
                    "testcase",
                    {"classname": src, "name": f.link.url},
                )
                msg = "; ".join(i.message for i in f.issues)
                codes = ",".join(i.code for i in f.issues)
                failure = SubElement(case, "failure", {"type": codes, "message": msg})
                failure.text = (
                    f"link={f.link.url}\n"
                    f"final_url={f.fetch.final_url}\n"
                    f"status={f.fetch.status}\n"
                    f"chain={' -> '.join(f.fetch.redirect_chain)}\n"
                )
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(suites, encoding="unicode")
