import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class TestPhase2GroupAndAlign(unittest.TestCase):
    def setUp(self):
        self.canvas_js = (ROOT / "static" / "js" / "canvas.js").read_text(encoding="utf-8")
        self.canvas_css = (ROOT / "static" / "css" / "canvas.css").read_text(encoding="utf-8")

    def test_frame_group_styles(self):
        self.assertIn(".frame-group-node", self.canvas_css)
        self.assertIn("border: 2px dashed var(--line-strong)", self.canvas_css)
        self.assertIn(".frame-group-header", self.canvas_css)
        self.assertIn(".frame-group-drag-handle", self.canvas_css)
        self.assertIn(".frame-group-resize-handle", self.canvas_css)
        self.assertIn(".frame-color-dot", self.canvas_css)

    def test_selection_hub_styles(self):
        self.assertIn(".selection-hub", self.canvas_css)
        self.assertIn(".selection-hub.open", self.canvas_css)
        self.assertIn(".hub-action-btn", self.canvas_css)
        self.assertIn(".hub-btn-group", self.canvas_css)

    def test_frame_group_functions(self):
        self.assertIn("function renderFrameGroupNode", self.canvas_js)
        self.assertIn("function createFrameGroup", self.canvas_js)
        self.assertIn("function ungroupFrameGroup", self.canvas_js)
        self.assertIn("function ungroupSelectedFrameGroups", self.canvas_js)
        self.assertIn("function startFrameGroupResize", self.canvas_js)

    def test_alignment_functions(self):
        self.assertIn("function alignSelectedNodes", self.canvas_js)
        self.assertIn("function distributeSelectedNodes", self.canvas_js)
        self.assertIn("function autoTidySelectedNodes", self.canvas_js)
        self.assertIn("function renderSelectionHub", self.canvas_js)

    def test_shortcuts_and_safety(self):
        # Ctrl+G creates frame_group, Ctrl+Shift+G ungroups
        self.assertIn("createFrameGroup();", self.canvas_js)
        self.assertIn("ungroupSelectedFrameGroups();", self.canvas_js)
        # Dragging moves children
        self.assertIn("dragTarget.type === 'frame_group'", self.canvas_js)

if __name__ == "__main__":
    unittest.main()
