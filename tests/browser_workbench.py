"""Use an isolated local session only; assertions read JSON, never scrape scores."""
import atexit
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaldesk/scripts"))
from workbench_core.self_test import fake_arbitration_payloads
from workbench_core.template import build_session

temporary = tempfile.TemporaryDirectory(prefix="evaldesk-browser-")
SESSION = Path(temporary.name) / "session"
ARTIFACTS = Path(temporary.name) / "artifacts"
SESSION.mkdir()
ARTIFACTS.mkdir(exist_ok=True)
payload, validation = fake_arbitration_payloads(
    output_count=15,
    row_count=10,
    reference_count=2,
    first_row_output_count=1,
)
manifest, tasks, results = build_session(
    "https://example.test/sheets/demo?sheet=sample",
    "sample",
    payload,
    validation,
    annotator="测试员",
)
for name, value in (
    ("manifest.json", manifest),
    ("tasks.json", tasks),
    ("results.json", results),
):
    (SESSION / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

server = subprocess.Popen(
    [
        sys.executable,
        str(ROOT / "evaldesk/scripts/serve_session.py"),
        "--session",
        str(SESSION),
        "--port",
        "0",
        "--no-open",
    ],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)


def cleanup():
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
    temporary.cleanup()


atexit.register(cleanup)
for _ in range(50):
    if (SESSION / "server.json").exists():
        break
    if server.poll() is not None:
        raise RuntimeError("EvalDesk test server exited before startup")
    time.sleep(0.1)
else:
    raise RuntimeError("Timed out waiting for EvalDesk test server")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(json.loads((SESSION / "server.json").read_text())["url"], wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle", timeout=30000)
    expect(page.locator(".reference-media")).to_have_count(2)
    expect(page.locator(".output-media")).to_have_count(1)
    page.screenshot(path=str(ARTIFACTS / "reference-layout.png"), full_page=True)

    # Both boundaries resize their adjacent panels; collapse state and widths persist.
    left = page.locator(".queue")
    center = page.locator(".review")
    right = page.locator(".annotation")
    left_before = left.bounding_box()["width"]
    center_before = center.bounding_box()["width"]
    left_handle = page.locator("#resizeLeft").bounding_box()
    page.mouse.move(left_handle["x"] + left_handle["width"] / 2, left_handle["y"] + 120)
    page.mouse.down()
    page.mouse.move(left_handle["x"] + 82, left_handle["y"] + 120, steps=4)
    page.mouse.up()
    assert left.bounding_box()["width"] > left_before + 60
    assert center.bounding_box()["width"] < center_before - 60

    right_before = right.bounding_box()["width"]
    center_before = center.bounding_box()["width"]
    right_handle = page.locator("#resizeRight").bounding_box()
    page.mouse.move(right_handle["x"] + right_handle["width"] / 2, right_handle["y"] + 120)
    page.mouse.down()
    page.mouse.move(right_handle["x"] - 72, right_handle["y"] + 120, steps=4)
    page.mouse.up()
    assert right.bounding_box()["width"] > right_before + 55
    assert center.bounding_box()["width"] < center_before - 55

    center_before = center.bounding_box()["width"]
    page.locator("#collapseLeft").click()
    expect(page.locator("#restoreLeft")).to_be_visible()
    expect(left).to_be_hidden()
    expect(page.locator("#resizeLeft")).to_be_hidden()
    expect(center).to_be_visible()
    assert center.bounding_box()["width"] > center_before + left_before
    page.locator("#restoreLeft").click()
    expect(left).to_be_visible()
    expect(page.locator("#resizeLeft")).to_be_visible()
    center_before = center.bounding_box()["width"]
    page.locator("#collapseRight").click()
    expect(page.locator("#restoreRight")).to_be_visible()
    expect(right).to_be_hidden()
    expect(page.locator("#resizeRight")).to_be_hidden()
    expect(center).to_be_visible()
    assert center.bounding_box()["width"] > center_before + right_before
    page.reload(wait_until="domcontentloaded")
    expect(right).to_be_hidden()
    expect(page.locator("#resizeRight")).to_be_hidden()
    expect(center).to_be_visible()
    page.locator("#restoreRight").click()
    expect(right).to_be_visible()
    expect(page.locator("#resizeRight")).to_be_visible()
    assert left.bounding_box()["width"] > left_before + 60
    page.screenshot(path=str(ARTIFACTS / "resizable-layout.png"), full_page=True)

    # Real 15-output fixture: user-driven horizontal scroll and clicks retain nodes.
    page.set_viewport_size({"width": 1024, "height": 900})
    right_handle = page.locator("#resizeRight").bounding_box()
    page.mouse.move(right_handle["x"] + right_handle["width"] / 2, right_handle["y"] + 120)
    page.mouse.down()
    page.mouse.move(right_handle["x"] + 180, right_handle["y"] + 120, steps=4)
    page.mouse.up()
    for _ in range(12):
        page.locator("#resizeRight").press("ArrowRight")
    page.locator('.task[data-row="5"]').click()
    tabs = page.locator("#outputTabs")
    tabs.hover()
    page.mouse.wheel(840, 0)
    page.get_by_role("button", name="结果 12", exact=True).scroll_into_view_if_needed()
    before = tabs.evaluate("(node) => node.scrollLeft")
    page.get_by_role("button", name="结果 12", exact=True).click()
    assert abs(tabs.evaluate("(node) => node.scrollLeft") - before) < 2
    expect(page.get_by_role("button", name="结果 12", exact=True)).to_have_class("active")
    dims = page.locator("#dimensionTabs")
    dims.evaluate("(node) => { node.scrollLeft = node.scrollWidth; }")
    before = dims.evaluate("(node) => node.scrollLeft")
    assert before > 0, "dimension test requires horizontal overflow"
    page.get_by_role("button", name="视觉审美", exact=True).click()
    assert abs(dims.evaluate("(node) => node.scrollLeft") - before) < 2
    output_scroll = tabs.evaluate("(node) => node.scrollLeft")
    page.locator(".score-grid button").filter(has_text="2").click()
    assert abs(tabs.evaluate("(node) => node.scrollLeft") - output_scroll) < 2

    # Switch before the debounce fires. Persist must retain the previous physical row.
    page.locator(".form textarea").first.fill("快速切换回归测试")
    page.locator('.task[data-row="6"]').click()
    expect(page.locator("#saveState")).to_have_text("本地已保存")
    saved = json.loads((SESSION / "results.json").read_text())
    assert saved["rows"]["5"]["dimensions"]["d5"]["reason"] == "快速切换回归测试"
    assert saved["rows"]["6"]["dimensions"]["d5"]["reason"] != "快速切换回归测试"

    # A failed request cannot navigate, mark green, or announce success.
    page.route("**/api/results", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error":"测试保存失败"}'))
    page.locator("#saveNext").click()
    expect(page.locator("#saveState")).to_contain_text("保存失败")
    expect(page.locator('.task[data-row="6"]')).not_to_have_class("saved")
    expect(page.locator("#title")).to_contain_text("第 6 行")
    page.unroute("**/api/results")
    page.locator("#saveNext").click()
    expect(page.locator("#title")).to_contain_text("第 7 行")
    expect(page.locator('.task[data-row="6"]')).to_have_class("task saved")
    page.set_viewport_size({"width": 1440, "height": 960})
    saved = json.loads((SESSION / "results.json").read_text())
    assert saved["rows"]["6"]["saved_at"]
    page.reload(wait_until="domcontentloaded")
    expect(page.locator('.task[data-row="6"]')).to_have_class("task saved")
    page.screenshot(path=str(ARTIFACTS / "saved-marker.png"), full_page=True)
    # Blind review must persist the independent snapshot before showing history.
    def blind_session(route):
        response = route.fetch()
        payload = response.json()
        payload["manifest"]["schema"]["blind"] = True
        route.fulfill(response=response, json=payload)
    page.route("**/api/session", blind_session)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".comparison-grid")).to_have_count(0)
    for name in ("指令跟随", "参考遵循", "画面质量", "文字质量", "视觉审美"):
        page.get_by_role("button", name=name, exact=True).click()
        page.locator(".score-grid button").filter(has_text="3").click()
    page.get_by_role("button", name="保存独立评分，进入 Review", exact=True).click()
    expect(page.locator(".comparison-grid")).to_have_count(1)
    saved = json.loads((SESSION / "results.json").read_text())
    assert saved["rows"]["4"]["blind_snapshot"]["dimensions"]["d1"]["human_score"] == ["3"]
    page.reload(wait_until="domcontentloaded")
    expect(page.locator(".comparison-grid")).to_have_count(1)
    page.unroute("**/api/session")
    page.locator("#collapseLeft").click()
    page.set_viewport_size({"width": 700, "height": 960})
    expect(left).to_be_visible()
    expect(page.locator("#resizeLeft")).to_be_hidden()
    assert not errors, errors
    browser.close()
cleanup()
atexit.unregister(cleanup)
print("browser regression: references, tabs, debounce, failure, green marker, reload, blind review — passed")
