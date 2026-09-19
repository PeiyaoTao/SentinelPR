"""No source/model HTML execution and lossless embedded report data."""
import base64
import hashlib
from html.parser import HTMLParser
import json
from sentinel.html_report import render_html, SCRIPT, STYLE
from sentinel.state import ConsolidatedReport


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.active = None
    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = [dict(attrs), ""]
            self.scripts.append(self.active)
    def handle_endtag(self, tag):
        if tag == "script": self.active = None
    def handle_data(self, data):
        if self.active is not None: self.active[1] += data


def test_malicious_source_cannot_close_embedded_data_script():
    source = '</script><script>alert("executed")</script><img src=x onerror=alert(1)>&'
    report = ConsolidatedReport(summary_markdown=source)
    html = render_html(report)
    document = Document()
    document.feed(html)
    assert len(document.scripts) == 2
    data = json.loads(document.scripts[0][1])
    assert data["summary_markdown"] == source
    assert source not in html
    assert "connect-src 'none'" in html
    assert "innerHTML" not in SCRIPT and "textContent" in SCRIPT


def test_csp_hashes_match_only_the_bundled_script_and_style():
    html = render_html(ConsolidatedReport(summary_markdown="test"))
    for content in (SCRIPT, STYLE):
        digest = base64.b64encode(hashlib.sha256(content.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in html
    assert "unsafe-inline" not in html
    assert 'src="http' not in html


def test_html_and_json_cli_exports_preserve_original_report(tmp_path):
    from sentinel.cli import _export_report
    report = ConsolidatedReport(summary_markdown="Unicode: 中文")
    html, data = tmp_path / "review.html", tmp_path / "review.json"
    _export_report(report, None, None, str(html), str(data))
    assert json.loads(data.read_text(encoding="utf-8"))["summary_markdown"] == report.summary_markdown
    assert "<!doctype html>" in html.read_text(encoding="utf-8")
