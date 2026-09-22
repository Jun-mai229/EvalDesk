#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
ARTIFACTS = Path(__file__).with_name(".artifacts")
ARTIFACTS.mkdir(exist_ok=True)


def assert_no_overflow(page) -> None:
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert not overflow, "页面存在水平溢出"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1440, "height": 1000},
        accept_downloads=True,
    )
    page = context.new_page()
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="打开演示任务").click()
    page.locator("#app").wait_for(state="visible")

    assert page.locator("#references figure").count() == 2
    assert page.locator("#outputs figure").count() == 2
    assert page.locator("#scoreBody select").count() == 16
    assert page.locator("#scoreBody .mos-input").count() == 2
    assert_no_overflow(page)
    page.screenshot(path=str(ARTIFACTS / "desktop.png"), full_page=True)

    page.locator("#reviewerName").fill("浏览器测试")
    for select in page.locator("#scoreBody select").all():
        select.select_option("5")
    for score in page.locator("#scoreBody .mos-input").all():
        score.fill("4.5")
    page.locator(".dimension-detail").first.locator("textarea").first.fill("自动保存测试")
    page.wait_for_timeout(300)
    assert page.evaluate("() => Boolean(localStorage.getItem('evaldesk-review:last-bundle'))")

    page.reload()
    page.wait_for_load_state("networkidle")
    page.locator("#app").wait_for(state="visible")
    assert page.locator("#reviewerName").input_value() == "浏览器测试"
    assert page.locator("#scoreBody select").first.input_value() == "5"
    assert page.locator(".dimension-detail").first.locator("textarea").first.input_value() == "自动保存测试"

    page.get_by_role("button", name="登记并下一条").click()
    assert page.locator(".task.registered").count() == 1
    assert "案例 DEMO-002" in page.locator("#taskTitle").inner_text()

    with page.expect_download() as download_info:
        page.get_by_role("button", name="导出结果").click()
    download = download_info.value
    export_path = ARTIFACTS / "downloaded-results.json"
    download.save_as(export_path)
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["review_package"]["package_id"] == "edr-public-demo"
    assert exported["reviewer"] == "浏览器测试"
    assert exported["rows"]["4"]["saved_at"]

    private_bundle = Path(__file__).with_name(".private") / "review-bundle.json"
    if private_bundle.exists():
        page.get_by_role("button", name="更换任务包").click()
        page.locator("#bundleInput").set_input_files(private_bundle)
        page.locator("#app").wait_for(state="visible")
        assert page.locator("#references figure").count() == 2
        assert page.locator("#outputs figure").count() == 1
        assert page.locator("#outputs video").count() == 1
        assert page.locator("#scoreBody select").count() == 8
        page.wait_for_function(
            "() => [...document.querySelectorAll('#references img')].every((img) => img.naturalWidth > 0)",
            timeout=15_000,
        )
        page.wait_for_function(
            "() => [...document.querySelectorAll('#outputs video')].every((video) => video.readyState > 0)",
            timeout=15_000,
        )
        page.screenshot(path=str(ARTIFACTS / "private-template.png"), full_page=True)

    mobile = context.new_page()
    mobile.set_viewport_size({"width": 390, "height": 844})
    mobile.goto(BASE_URL)
    mobile.wait_for_load_state("networkidle")
    mobile.locator("#app").wait_for(state="visible")
    assert mobile.locator("#outputs figure").count() == 1
    assert_no_overflow(mobile)
    mobile.screenshot(path=str(ARTIFACTS / "mobile.png"), full_page=True)

    assert not console_errors, f"浏览器控制台错误: {console_errors}"
    browser.close()

print("browser checks passed")
