import re
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class TestPhase1AgentAtmosphere(unittest.TestCase):
    def test_canvas_html_has_atmosphere_btn(self):
        html_path = ROOT / "static" / "canvas.html"
        self.assertTrue(html_path.exists(), "static/canvas.html should exist")
        content = html_path.read_text(encoding="utf-8")
        self.assertIn('id="agentExtractAtmosphereBtn"', content)
        self.assertIn('data-i18n="canvas.agentExtractAtmosphere"', content)

    def test_i18n_has_atmosphere_keys(self):
        i18n_path = ROOT / "static" / "js" / "i18n" / "canvas.js"
        content = i18n_path.read_text(encoding="utf-8")
        self.assertIn('"canvas.agentExtractAtmosphere"', content)
        self.assertIn('"canvas.copyJson"', content)
        self.assertIn('"canvas.createPromptFromAtmosphere"', content)

    def test_canvas_agent_js_contains_atmosphere_logic(self):
        agent_js_path = ROOT / "static" / "js" / "canvas-agent.js"
        content = agent_js_path.read_text(encoding="utf-8")
        self.assertIn("agentExtractAtmosphereBtn", content)
        self.assertIn("handleExtractAtmosphere", content)
        self.assertIn("extractAtmosphereJson", content)
        self.assertIn("formatAtmospherePrompt", content)
        self.assertIn("agent-atmosphere-prompt-node-btn", content)
        self.assertIn("agent-copy-json-btn", content)
        self.assertIn("style_and_atmosphere", content)
        self.assertIn("spatial_content_breakdown", content)

    def test_canvas_css_has_json_bubble_styles(self):
        css_path = ROOT / "static" / "css" / "canvas.css"
        content = css_path.read_text(encoding="utf-8")
        self.assertIn(".agent-json-bubble", content)
        self.assertIn(".agent-json-header", content)
        self.assertIn(".agent-json-pre", content)

if __name__ == "__main__":
    unittest.main()
