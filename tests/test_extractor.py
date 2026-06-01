from findbrokenlinks.extractors.html import HTMLExtractor

HTML = """
<html><head>
<base href="https://example.com/sub/">
<link rel="stylesheet" href="/style.css">
</head>
<body>
<a href="page.html">page</a>
<a href="https://other.com/x">other</a>
<a href="#frag">frag-only</a>
<a href="mailto:a@b.c">mail</a>
<img src="/img.png" alt="image">
<script src="//cdn.example.com/x.js"></script>
</body></html>
"""


def test_extracts_a_img_script_link_with_base_href():
    ext = HTMLExtractor()
    links = list(ext.extract(HTML, source_page="https://example.com/index.html"))
    urls = {(link.tag, link.url) for link in links}
    # <base href> resolves relative URLs.
    assert ("a", "https://example.com/sub/page.html") in urls
    assert ("a", "https://other.com/x") in urls
    # /style.css resolves against base href (absolute path → host of base).
    assert ("link", "https://example.com/style.css") in urls
    assert ("img", "https://example.com/img.png") in urls
    assert ("script", "https://cdn.example.com/x.js") in urls
    # Skipped: pure fragment, mailto.
    assert not any(u.startswith("mailto:") for _, u in urls)
    assert not any("#frag" in u for _, u in urls)
