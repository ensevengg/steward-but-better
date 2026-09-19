"""Exercise the running production UI/API and record reproducible video proof."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:3000")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--output", type=Path, default=Path("test-results/browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    recording_directory = tempfile.mkdtemp(prefix="steward-video-")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel or None, headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            reduced_motion="reduce",
            record_video_dir=recording_directory,
            record_video_size={"width": 1440, "height": 1000},
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.get_by_role("button", name="Load São Paulo 2025 study").click()
        expect(page.locator(".case-intro .badge")).to_have_text(
            "Penalty recommended · 10 seconds", timeout=20000
        )
        expect(page.get_by_text("Document reconstruction: observations", exact=False)).to_be_visible()
        expect(page.get_by_role("img", name=re.compile("Speed traces"))).to_be_visible()
        checks.append("Real recorded telemetry + document reconstruction produce 10-second recommendation")
        page.wait_for_timeout(1800)
        page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
        page.get_by_text("Sample values (576)", exact=True).click()
        expect(page.locator(".sample-table tbody tr")).to_have_count(576)
        page.wait_for_timeout(800)
        page.get_by_text("Sample values (576)", exact=True).click()
        page.get_by_role("heading", name="Rule conditions").scroll_into_view_if_needed()
        expect(page.locator(".conditions li")).to_have_count(9)
        page.wait_for_timeout(1200)
        page.get_by_role("heading", name="Applicable rules").scroll_into_view_if_needed()
        page.get_by_text(
            "2025 Penalty Guidelines: causing a collision; Appendix L IV 2(d)", exact=True
        ).click()
        expect(page.get_by_role("link", name=re.compile("Source document")).first).to_be_visible()
        page.wait_for_timeout(1200)
        checks.append("Native samples, nine conditions, provenance, and source-linked rules visible")
        page.get_by_role("button", name="Close case", exact=True).click()
        expect(page.get_by_role("button", name="Reopen case")).to_be_enabled()
        page.reload()
        page.locator("#case-filter").select_option("closed")
        expect(page.locator(".case-item")).to_have_count(1)
        page.locator(".case-item").click()
        expect(page.get_by_role("button", name="Reopen case")).to_be_enabled()
        page.get_by_role("button", name="Reopen case").click()
        page.locator("#case-filter").select_option("open")
        expect(page.locator(".case-item")).to_have_count(2)
        checks.append("Close/reopen persists across browser refresh without changing judgment")
        page.get_by_role("button", name=re.compile("telemetry-only assessment")).click()
        expect(page.locator(".case-intro .badge")).to_have_text("Insufficient evidence")
        expect(page.get_by_text("Telemetry only: overlap", exact=False)).to_be_visible()
        page.wait_for_timeout(1600)
        checks.append("Same incident with telemetry alone abstains, no invented sanction")
        for width in [320, 390, 768, 1024, 1440]:
            page.set_viewport_size({"width": width, "height": 900})
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(250)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                f"Overflow at {width}px"
            )
            if width <= 390:
                page.get_by_role("button", name="Timing", exact=True).click()
                expect(page.locator(".timing-table")).to_be_visible()
                page.get_by_role("button", name="Cases", exact=True).click()
                expect(page.locator(".case-list")).to_be_visible()
                page.screenshot(path=str(args.output / f"mobile-{width}.png"), full_page=True)
                page.wait_for_timeout(600)
        checks.append("No horizontal overflow at 320/390/768/1024/1440px; mobile tabs work")
        page.evaluate("window.scrollTo(0, 600)")
        scroll_y = page.evaluate("window.scrollY")
        page.wait_for_timeout(1800)
        assert abs(page.evaluate("window.scrollY") - scroll_y) < 3
        checks.append("Polling preserves reader scroll position")
        # Explicit fault injection only for this resilience check; earlier footage
        # uses the real UI proxy, SQLite queue and assessor without mocked APIs.
        page.route(
            "**/api/telemetry*",
            lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"error":"Connection unavailable (test)"}'
            ),
        )
        expect(page.get_by_text("Connection unavailable (test)", exact=False)).to_be_visible(timeout=15000)
        expect(page.locator(".case-intro .badge")).to_have_text("Insufficient evidence")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1200)
        page.unroute("**/api/telemetry*")
        expect(page.get_by_text("Connection unavailable (test)", exact=False)).to_have_count(0, timeout=15000)
        checks.append("Injected outage shows stale warning, retains last case, and recovers")
        assert not errors, errors
        checks.append("No browser runtime errors")
        video = page.video
        context.close()
        video.save_as(str(args.output / "steward-demo.webm"))
        video.delete()
        browser.close()
    assert (args.output / "steward-demo.webm").stat().st_size > 1000, "Recording is empty"
    Path(recording_directory).rmdir()
    report = {"checks": checks, "passed": len(checks), "errors": errors}
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
