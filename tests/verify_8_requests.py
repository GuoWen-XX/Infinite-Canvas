import os
import time
from playwright.sync_api import sync_playwright

ARTIFACT_DIR = r"C:\Users\shimi\.gemini\antigravity\brain\d4c92dc8-f01a-4dd7-a01f-11f60d4b43de"

def run_verification():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = context.new_page()

        print("1. Checking index.html stage border-radius...")
        page.goto("http://127.0.0.1:3000/static/index.html")
        page.wait_for_selector(".stage", timeout=10000)
        time.sleep(1)

        # Req 6: Check stage border-radius
        stage_border_radius = page.eval_on_selector(".stage", "el => getComputedStyle(el).borderRadius")
        print(f"[Req 6] Stage border-radius: {stage_border_radius}")
        assert stage_border_radius == "6px", f"Expected 6px, got {stage_border_radius}"
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "verify_stage_radius.png"))

        # Navigate directly to canvas.html with test canvas ID
        print("2. Navigating to canvas.html...")
        page.goto("http://127.0.0.1:3000/static/canvas.html?id=1260ed920f6949b5b7c4c5314316ce93")
        page.wait_for_selector(".node", timeout=10000)
        time.sleep(1.5)

        # Req 1: Warm theme button background color (coffee brown)
        page.evaluate("() => { applyTheme('warm'); }")
        time.sleep(0.5)
        warm_btn_bg = page.eval_on_selector(".node .gen-btn", "el => getComputedStyle(el).backgroundColor")
        print(f"[Req 1] Warm theme button background: {warm_btn_bg}")
        assert "69, 50, 37" in warm_btn_bg, f"Expected coffee color (rgb(69, 50, 37)), got {warm_btn_bg}"
        page.locator(".node").first.screenshot(path=os.path.join(ARTIFACT_DIR, "verify_warm_button.png"))

        # Req 3: Dark theme Bauhaus grayscale
        page.evaluate("() => { applyTheme('dark'); }")
        time.sleep(0.5)
        dark_card_bg = page.eval_on_selector(".node", "el => getComputedStyle(el).backgroundColor")
        dark_head_bg = page.eval_on_selector(".node .node-head", "el => getComputedStyle(el).backgroundColor")
        dark_btn_bg = page.eval_on_selector(".node .gen-btn", "el => getComputedStyle(el).backgroundColor")
        dark_btn_color = page.eval_on_selector(".node .gen-btn", "el => getComputedStyle(el).color")
        dark_port_bg = page.eval_on_selector(".port", "el => getComputedStyle(el, '::after').backgroundColor")
        print(f"[Req 3] Dark mode card bg: {dark_card_bg}, head bg: {dark_head_bg}, btn bg: {dark_btn_bg}, btn color: {dark_btn_color}")
        print(f"[Req 3] Dark mode port::after: {dark_port_bg}")
        assert "33, 33, 33" in dark_card_bg, f"Expected #212121, got {dark_card_bg}"
        assert "41, 41, 41" in dark_head_bg, f"Expected #292929, got {dark_head_bg}"
        assert "245, 245, 245" in dark_btn_bg, f"Expected #f5f5f5 button, got {dark_btn_bg}"
        assert "16, 16, 16" in dark_btn_color, f"Expected #101010 text, got {dark_btn_color}"
        assert "245, 245, 245" in dark_port_bg, f"Expected #f5f5f5 port, got {dark_port_bg}"
        page.locator(".node").first.screenshot(path=os.path.join(ARTIFACT_DIR, "verify_dark_node.png"))

        # Req 7: Output port position outside card
        port_out_right = page.eval_on_selector(".port.out", "el => getComputedStyle(el).right")
        print(f"[Req 7] Output port right offset: {port_out_right}")
        assert port_out_right == "-29px", f"Expected -29px, got {port_out_right}"

        # Req 2 & 4: Agent default provider and Dock side toggle
        page.evaluate("() => { if(window.CanvasAgent && window.CanvasAgent.toggle) window.CanvasAgent.toggle(true); }")
        time.sleep(0.5)

        provider_val = page.eval_on_selector("#agentProviderSelect", "el => el.value")
        print(f"[Req 2] Agent default provider: {provider_val}")
        assert provider_val == "gemini-cli", f"Expected gemini-cli, got {provider_val}"

        dock_btn = page.locator("#agentDockSideBtn")
        assert dock_btn.count() > 0, "Dock button not found"
        print("[Req 4] Testing Agent dock switch to right...")
        dock_btn.click()
        time.sleep(0.5)
        has_dock_right = page.eval_on_selector("#canvasAgentPanel", "el => el.classList.contains('dock-right')")
        print(f"[Req 4] Panel has .dock-right: {has_dock_right}")
        assert has_dock_right, "Expected panel to have dock-right class"
        page.screenshot(path=os.path.join(ARTIFACT_DIR, "verify_agent_dock_right.png"))

        print("[Req 4] Testing Agent dock switch back to left...")
        dock_btn.click()
        time.sleep(0.5)
        has_dock_left = not page.eval_on_selector("#canvasAgentPanel", "el => el.classList.contains('dock-right')")
        print(f"[Req 4] Panel back to left side: {has_dock_left}")
        assert has_dock_left, "Expected panel to be back on left"

        # Req 5: Generation Log and 6px border-radius
        page.evaluate("() => { if(window.openCanvasLog) window.openCanvasLog(); }")
        time.sleep(1.5)
        log_panel_radius = page.eval_on_selector(".log-panel", "el => getComputedStyle(el).borderRadius")
        print(f"[Req 5] Log panel border-radius: {log_panel_radius}")
        assert log_panel_radius == "6px", f"Expected 6px, got {log_panel_radius}"

        log_items_count = page.locator(".log-item").count()
        print(f"[Req 5] Log items rendered: {log_items_count}")
        if log_items_count > 0:
            item_radius = page.eval_on_selector(".log-item", "el => getComputedStyle(el).borderRadius")
            print(f"[Req 5] Log item border-radius: {item_radius}")
            assert item_radius == "6px", f"Expected 6px, got {item_radius}"
        page.locator("#logModal").screenshot(path=os.path.join(ARTIFACT_DIR, "verify_log_panel.png"))
        page.evaluate("() => { if(window.closeCanvasLog) window.closeCanvasLog(); }")
        time.sleep(0.5)

        # Req 8: Context menu collapsed section hover flyout
        page.evaluate("() => { if(window.openCreateMenu) window.openCreateMenu(300, 300); }")
        time.sleep(0.5)

        img_section = page.locator(".menu-section[data-section='image']")
        if not page.eval_on_selector(".menu-section[data-section='image']", "el => el.classList.contains('collapsed')"):
            page.locator(".menu-section[data-section='image'] .menu-section-header").click()
            time.sleep(0.3)

        is_collapsed = page.eval_on_selector(".menu-section[data-section='image']", "el => el.classList.contains('collapsed')")
        print(f"[Req 8] Menu section image is collapsed: {is_collapsed}")
        assert is_collapsed, "Expected section to be collapsed"

        img_section.hover()
        time.sleep(0.5)

        body_display = page.eval_on_selector(".menu-section[data-section='image'] .menu-section-body", "el => getComputedStyle(el).display")
        body_pos = page.eval_on_selector(".menu-section[data-section='image'] .menu-section-body", "el => getComputedStyle(el).position")
        print(f"[Req 8] Hovered body display: {body_display}, position: {body_pos}")
        assert body_display == "flex", f"Expected flex display on hover, got {body_display}"
        assert body_pos == "absolute", f"Expected absolute positioning on hover, got {body_pos}"

        page.locator("#createMenu").screenshot(path=os.path.join(ARTIFACT_DIR, "verify_menu_hover_flyout.png"))

        browser.close()
        print("\n========================================================")
        print("ALL 8 USER REQUIREMENTS 100% VERIFIED AND PASSING!")
        print("========================================================")

if __name__ == "__main__":
    run_verification()
