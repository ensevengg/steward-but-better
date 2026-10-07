"""Verify the whole field stays visible and updating while side-panel cases are reviewed."""

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
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="steward-field-video-") as recording, sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel or None, headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce",
            record_video_dir=recording,
            record_video_size={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        page.get_by_role("button", name="Replay full field", exact=True).click()
        expect(page.get_by_test_id("driver-card")).to_have_count(20)
        for width, height in [(1440, 900), (1366, 768)]:
            page.set_viewport_size({"width": width, "height": height})
            assert page.get_by_test_id("driver-card").evaluate_all(
                "cards => cards.every(c => c.getBoundingClientRect().bottom <= innerHeight && c.getBoundingClientRect().top >= 0 && c.scrollHeight <= c.clientHeight + 1)"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1440, "height": 900})
        before = page.get_by_test_id("sample-count").inner_text()
        expect(page.get_by_test_id("sample-count")).not_to_have_text(before, timeout=5000)
        checks.append(
            "All 20 real driver cards visible without scrolling at desktop/laptop sizes; native counts advance"
        )
        page.wait_for_timeout(1500)
        page.screenshot(path=str(args.output / "desktop.png"))

        # Explicit test submission. It does not change the live session or claim detection.
        session = page.get_by_role("combobox", name="Session", exact=True).input_value()
        case = json.loads((root / "benchmarks/sao_paulo_2025.json").read_text(encoding="utf-8"))
        case.update(
            id=f"{session}:browser-reviewed",
            session_id=session,
            title="Judging test · reviewed São Paulo reconstruction",
        )
        case["samples"] = json.loads(
            (root / "benchmarks/sao_paulo_2025_telemetry.json").read_text(encoding="utf-8")
        )["samples"]
        assert page.request.post(f"{args.url}/api/investigations", data=case).status == 202
        telemetry = {
            **case,
            "id": f"{session}:browser-raw",
            "title": "Judging test · telemetry-only control",
            "observations": [],
            "evidence_mode": "telemetry_only",
        }
        assert page.request.post(f"{args.url}/api/investigations", data=telemetry).status == 202
        expect(page.locator(".case-item")).to_have_count(2, timeout=15000)
        page.get_by_role("button", name=re.compile("Judging test · reviewed")).click()
        expect(page.locator(".case-intro .badge")).to_have_text(
            "Penalty recommended · 10 seconds", timeout=15000
        )
        expect(page.get_by_text("Document reconstruction: observations", exact=False)).to_be_visible()
        before = page.get_by_test_id("sample-count").inner_text()
        expect(page.get_by_test_id("sample-count")).not_to_have_text(before, timeout=5000)
        expect(page.get_by_test_id("driver-card")).to_have_count(20)
        checks.append(
            "Reviewed 10-second test case opens only in sidebar; all-car telemetry continues advancing"
        )
        page.wait_for_timeout(1300)
        page.screenshot(path=str(args.output / "with-report.png"))
        page.get_by_text("Sample values (576)", exact=True).click()
        expect(page.locator(".sample-table tbody tr")).to_have_count(576)
        page.get_by_text("Sample values (576)", exact=True).click()
        page.get_by_text("Applicable rules", exact=True).click()
        expect(page.get_by_role("link", name=re.compile("Source document")).first).to_be_visible()
        assert page.get_by_test_id("driver-card").first.bounding_box()["y"] > 0
        checks.append("Sidebar scroll exposes samples/rules without moving or hiding the field")
        page.get_by_role("button", name="Close case", exact=True).click()
        expect(page.get_by_role("button", name="Reopen case")).to_be_enabled()
        page.reload()
        page.locator("#case-filter").select_option("closed")
        expect(page.locator(".case-item")).to_have_count(1)
        page.locator(".case-item").click()
        page.get_by_role("button", name="Reopen case").click()
        expect(page.get_by_role("button", name="Close case")).to_be_enabled()
        page.get_by_role("button", name="All reports", exact=False).click()
        page.locator("#case-filter").select_option("open")
        page.get_by_role("button", name=re.compile("telemetry-only control")).click()
        expect(page.locator(".case-intro .badge")).to_have_text("Insufficient evidence")
        checks.append("Persistent close/reopen and telemetry-only abstention still work in report rail")
        page.wait_for_timeout(1000)
        for width in [320, 390, 768, 1024, 1440]:
            page.set_viewport_size({"width": width, "height": 900})
            page.wait_for_timeout(200)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}"
            if width <= 900:
                page.get_by_role("button", name="All drivers", exact=True).click()
                expect(page.get_by_test_id("driver-card")).to_have_count(20)
                expect(page.get_by_test_id("driver-card").first).to_be_visible()
                page.screenshot(path=str(args.output / f"mobile-{width}.png"))
                page.get_by_role("button", name=re.compile(r"^Reports \(")).click()
                expect(page.locator(".case-intro .badge")).to_be_visible()
        checks.append("Responsive field/report tabs work with no overflow at 320/390/768/1024/1440px")
        page.route(
            "**/api/telemetry*",
            lambda route: route.fulfill(
                status=503, content_type="application/json", body='{"error":"Connection unavailable (test)"}'
            ),
        )
        expect(page.get_by_text("Connection unavailable (test)", exact=False)).to_be_visible(timeout=10000)
        expect(page.get_by_test_id("driver-card")).to_have_count(20)
        page.wait_for_timeout(1000)
        page.unroute("**/api/telemetry*")
        expect(page.get_by_text("Connection unavailable (test)", exact=False)).to_have_count(0, timeout=10000)
        checks.append("Injected outage labels stale data, keeps all 20 cards, and recovers")
        assert not errors, errors
        checks.append("No browser runtime errors")
        video = page.video
        context.close()
        video.save_as(str(args.output / "steward-demo.webm"))
        video.delete()
        browser.close()
    assert (args.output / "steward-demo.webm").stat().st_size > 1000, "Empty recording"
    report = {
        "checks": checks,
        "passed": len(checks),
        "errors": errors,
        "scope": "Real 20-driver excerpt; two judging cases explicitly submitted as tests",
    }
    (args.output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
