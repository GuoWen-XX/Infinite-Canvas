import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class TestStep3CanvasAndToggles(unittest.TestCase):
    def test_sidebar_has_granular_nav_ids(self):
        index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        shell_js = ROOT / "static" / "js" / "studio-shell.js"
        if shell_js.exists():
            index_html += shell_js.read_text(encoding="utf-8")
        self.assertIn('id="nav-item-zimage"', index_html)
        self.assertIn('id="nav-item-enhance"', index_html)
        self.assertIn('id="nav-item-klein"', index_html)
        self.assertIn('id="nav-item-angle"', index_html)
        self.assertIn('id="nav-item-online"', index_html)
        self.assertIn('showZimage', index_html)
        self.assertIn('showEnhance', index_html)
        self.assertIn('showKlein', index_html)
        self.assertIn('showAngle', index_html)

    def test_api_settings_modules_defs(self):
        js = (ROOT / "static" / "js" / "api-settings.js").read_text(encoding="utf-8")
        self.assertIn('id: "zimage"', js)
        self.assertIn('id: "enhance"', js)
        self.assertIn('id: "klein"', js)
        self.assertIn('id: "angle"', js)
        self.assertIn('id: "online"', js)
        self.assertIn('state.zimage = false;', js)
        self.assertIn('state.enhance = false;', js)

    def test_canvas_html_has_native_preset_buttons(self):
        canvas_html = (ROOT / "static" / "canvas.html").read_text(encoding="utf-8")
        self.assertIn('onclick="addEnhanceNode()"', canvas_html)
        self.assertIn('onclick="addAngleNode()"', canvas_html)
        self.assertIn('onclick="addEditNode()"', canvas_html)
        self.assertIn("onclick=\"menuAdd('enhance')\"", canvas_html)
        self.assertIn("onclick=\"menuAdd('angle')\"", canvas_html)
        self.assertIn("onclick=\"menuAdd('edit')\"", canvas_html)

    def test_canvas_js_has_preset_functions(self):
        canvas_js = (ROOT / "static" / "js" / "canvas.js").read_text(encoding="utf-8")
        self.assertIn("function addEnhanceNode(", canvas_js)
        self.assertIn("function addAngleNode(", canvas_js)
        self.assertIn("function addEditNode(", canvas_js)
        self.assertIn("type === 'enhance'", canvas_js)
        self.assertIn("type === 'angle'", canvas_js)
        self.assertIn("type === 'edit'", canvas_js)

    def test_smart_canvas_has_preset_cards(self):
        smart_html = (ROOT / "static" / "smart-canvas.html").read_text(encoding="utf-8")
        self.assertIn('data-create-type="enhance"', smart_html)
        self.assertIn('data-create-type="angle"', smart_html)
        self.assertIn('data-create-type="edit"', smart_html)
        smart_js = (ROOT / "static" / "js" / "smart-canvas.js").read_text(encoding="utf-8")
        self.assertIn("type === 'enhance'", smart_js)
        self.assertIn("type === 'angle'", smart_js)
        self.assertIn("type === 'edit'", smart_js)

    def test_i18n_keys(self):
        api_i18n = (ROOT / "static" / "js" / "i18n" / "api-settings.js").read_text(encoding="utf-8")
        self.assertIn('"api.moduleZimage"', api_i18n)
        self.assertIn('"api.moduleEnhance"', api_i18n)
        self.assertIn('"api.moduleKlein"', api_i18n)
        self.assertIn('"api.moduleAngle"', api_i18n)

        canvas_i18n = (ROOT / "static" / "js" / "i18n" / "canvas.js").read_text(encoding="utf-8")
        self.assertIn('"canvas.enhanceNode"', canvas_i18n)
        self.assertIn('"canvas.angleNode"', canvas_i18n)
        self.assertIn('"canvas.editNode"', canvas_i18n)

if __name__ == "__main__":
    unittest.main()
