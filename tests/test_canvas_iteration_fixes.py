"""Tests for the 4 user feedback adjustments:
1. Tool dock moved to left vertical
2. Pen vs Hand dragging separation (Spacebar pan, middle click pan)
3. Translucent frosted glass styling on sketch toolbars
4. Reverse prompt interrogation in strict JSON format
"""

import os
import json
import unittest

class TestCanvasIterationFixes(unittest.TestCase):
    def test_tool_dock_is_vertical_on_left(self):
        css_path = os.path.join("static", "css", "canvas.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".canvas-tool-dock", css)
        # Check left vertical positioning
        self.assertTrue("left: 20px" in css or "left: 24px" in css)
        self.assertIn("flex-direction: column", css)

    def test_sketch_toolbars_are_translucent(self):
        css_path = os.path.join("static", "css", "canvas.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        # Check frosted glass blur and semi-transparent alpha backgrounds
        self.assertTrue("backdrop-filter: blur(20px)" in css or "backdrop-filter: blur(24px)" in css)
        self.assertTrue("rgba(255, 255, 255, 0.72)" in css or "rgba(24, 24, 27, 0.72)" in css)
        self.assertIn(".sketch-property-inspector", css)
        self.assertIn(".sketch-quick-action", css)

    def test_hand_and_space_pan_cursors(self):
        css_path = os.path.join("static", "css", "canvas.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".board.sketch-drawing-mode", css)
        self.assertIn(".board.sketch-hand-mode", css)
        self.assertIn(".board.sketch-space-pan", css)
        self.assertIn("cursor: crosshair !important", css)
        self.assertIn("cursor: grab !important", css)
        self.assertIn("cursor: grabbing !important", css)

    def test_space_pan_and_hand_handling_in_js(self):
        js_path = os.path.join("static", "js", "canvas-sketch.js")
        with open(js_path, "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("isSpaceHeld", code)
        self.assertIn("sketch-space-pan", code)
        self.assertIn("startBoardPan", code)
        self.assertIn("onKeyUp", code)

    def test_reverse_prompt_interrogation_is_json_format(self):
        agent_js_path = os.path.join("static", "js", "canvas-agent.js")
        with open(agent_js_path, "r", encoding="utf-8") as f:
            code = f.read()

        # handleInterrogate requests JSON format
        self.assertIn("JSON Code Block only", code)
        self.assertIn("prompt_zh", code)
        self.assertIn("prompt_en", code)
        self.assertIn("visual_analysis", code)

        # extractAtmosphereJson / structured JSON parser recognizes reverse prompt JSON
        self.assertIn("isInterrogate", code)
        self.assertIn("反推生图提示词", code)

if __name__ == "__main__":
    unittest.main()
