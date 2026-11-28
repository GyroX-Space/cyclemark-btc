"""Deployment contract: CMCI at the site root, CycleMark BTC at /cyclemark/."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMARY_PAGE = ROOT / "web" / "index.html"
LEGACY_PAGE = ROOT / "web" / "cyclemark" / "index.html"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
DAILY_SCRIPT = ROOT / "scripts" / "run_daily.sh"


def test_cmci_is_the_primary_page_and_links_the_secondary_product():
    html = PRIMARY_PAGE.read_text(encoding="utf-8")
    assert "CMCI" in html
    assert "Crypto Market Cycle Intelligence" in html
    assert html.count("data-secondary-link") >= 3
    assert 'href="cyclemark/"' in html


def test_legacy_dashboard_links_back_to_cmci():
    html = LEGACY_PAGE.read_text(encoding="utf-8")
    assert "CYCLEMARK BTC" in html
    assert '<a class="pill" href="../"' in html


def test_pages_workflow_publishes_the_primary_page():
    workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
    assert "cp web/index.html site/index.html" in workflow
    assert "cp -R data/signals site/data/signals" in workflow


def test_daily_publish_installs_both_products():
    script = DAILY_SCRIPT.read_text(encoding="utf-8")
    assert 'web/index.html "$WEB_ROOT/index.html"' in script
    assert 'web/cyclemark/index.html "$WEB_ROOT/cyclemark/index.html"' in script
    assert '"$WEB_ROOT/cyclemark/i18n/"' in script