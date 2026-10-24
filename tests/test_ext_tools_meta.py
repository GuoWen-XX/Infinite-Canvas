import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestExtToolsMeta(unittest.TestCase):
    def test_meta_js_file_exists(self):
        js_path = ROOT / "static" / "js" / "ext-tools-meta.js"
        self.assertTrue(js_path.exists(), f"File not found: {js_path}")

    def test_all_44_tools_defined_and_assets_exist(self):
        js_path = ROOT / "static" / "js" / "ext-tools-meta.js"
        self.assertTrue(js_path.exists(), f"File not found: {js_path}")
        content = js_path.read_text(encoding="utf-8")

        expected_ids = [
            "mai", "copilot", "arena", "reve", "gflow", "grok",
            "qianwen", "chatgpt", "rh-canvas", "rh-user", "cloudcb",
            "ascii", "ladybug", "boardmix", "canva", "longcat",
            "dola", "agnes-wb", "lovart", "topaz", "tooootem",
            "feralui", "valessa",
            "google-pics", "mindvideo", "gen-design", "shadergpt", "sensenova",
            "fal-ai", "aihubmix", "omniakey", "eachlabs", "apikey-fun", "merge-gateway",
            "animos", "brand-gen", "adam", "cutia", "opencut",
            "motion-dev", "minimax-h3", "openprocessing", "gen-gestaltung", "recent-design",
            "codrops-gsap", "artificial-lab",
            "brik-space", "asc11", "design-arena", "snitscanner", "spinespine",
            "intr-pattern", "tooooools", "effect-app", "gianluca-sketches", "digitiles",
            "pixelsynth", "fontbox", "pixel-perfect", "divisare", "kontextur",
            "gradient-lab", "bg-freebies", "ascii-magic", "dotforge", "duck-ai",
            "flux-tools", "flux-precise", "brik-editor", "brik-mousegrid", "aholo3d", "artcraft"
        ]
        self.assertEqual(len(expected_ids), 72)

        # Ensure window.EXT_TOOL_META is defined
        self.assertIn("window.EXT_TOOL_META", content)

        # Inspect each tool block
        for tid in expected_ids:
            self.assertIn(f'"{tid}":', content, f"Tool ID '{tid}' missing in EXT_TOOL_META")
            # Extract block for tid
            tool_pattern = re.compile(rf'"{re.escape(tid)}"\s*:\s*\{{([^}}]+)\}}')
            tm = tool_pattern.search(content)
            self.assertIsNotNone(tm, f"Could not parse block for '{tid}'")
            block = tm.group(1)

            for req_field in ["id", "name", "nameZh", "url", "domain", "category", "desc", "preview"]:
                field_pattern = re.compile(rf'(?:"{req_field}"|{req_field})\s*:')
                self.assertRegex(block, field_pattern, f"Field '{req_field}' missing in tool '{tid}'")

            # Validate preview asset exists and is non-empty
            preview_match = re.search(r'(?:"preview"|preview)\s*:\s*"([^"]+)"', block)
            self.assertIsNotNone(preview_match, f"Could not extract preview path for '{tid}'")
            preview_val = preview_match.group(1)
            self.assertTrue(
                preview_val.startswith("/static/images/ext-previews/"),
                f"Preview path must start with /static/images/ext-previews/, got: {preview_val}"
            )
            self.assertTrue(
                preview_val.endswith(".png"),
                f"Preview path must end with .png, got: {preview_val}"
            )

            asset_rel = preview_val.lstrip("/")
            asset_path = ROOT / asset_rel
            self.assertTrue(asset_path.exists(), f"Preview asset does not exist on disk: {asset_path}")
            self.assertGreater(asset_path.stat().st_size, 0, f"Preview asset is 0 bytes: {asset_path}")

        # Assert all preview files in directory are .png
        preview_dir = ROOT / "static" / "images" / "ext-previews"
        for pf in preview_dir.iterdir():
            self.assertEqual(pf.suffix, ".png", f"Preview file must be .png: {pf.name}")

        # Check for zero colorful emojis
        emoji_pattern = re.compile(
            r"[\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF\u2702-\u27B0]"
        )
        emoji_matches = emoji_pattern.findall(content)
        self.assertEqual(len(emoji_matches), 0, f"Found illegal colorful emojis in EXT_TOOL_META: {emoji_matches}")

    def test_index_html_contains_new_tabs(self):
        html_path = ROOT / "static" / "index.html"
        self.assertTrue(html_path.exists(), f"File not found: {html_path}")
        html = html_path.read_text(encoding="utf-8")
        shell_js = ROOT / "static" / "js" / "studio-shell.js"
        if shell_js.exists():
            html += "\n" + shell_js.read_text(encoding="utf-8")
        shell_css = ROOT / "static" / "css" / "studio-shell.css"
        if shell_css.exists():
            html += "\n" + shell_css.read_text(encoding="utf-8")

        # 1. ext-tools-meta.js script tag (may include ?v= cache-busting stamp)
        self.assertTrue('src="/static/js/ext-tools-meta.js' in html, "Missing ext-tools-meta.js script tag in index.html")

        # 2. ext-folder-count = 72
        self.assertTrue('id="ext-folder-count">72<' in html, "ext-folder-count is not 72 in index.html")

        # 3. DOM tabs for feralui, valessa, and newly added tools
        for tab_id, onclick_fn, i18n_key in [
            ("feralui", "openFeralUi(this)", "nav.feralui"),
            ("valessa", "openValessa(this)", "nav.valessa"),
            ("google-pics", "openGooglePics(this)", "nav.googlePics"),
            ("mindvideo", "openMindVideo(this)", "nav.mindvideo"),
            ("gen-design", "openGenDesign(this)", "nav.genDesign"),
            ("shadergpt", "openShaderGpt(this)", "nav.shadergpt"),
            ("sensenova", "openSenseNova(this)", "nav.sensenova"),
            ("fal-ai", "openFalAi(this)", "nav.falAi"),
            ("aihubmix", "openAihubmix(this)", "nav.aihubmix"),
            ("omniakey", "openOmniakey(this)", "nav.omniakey"),
            ("eachlabs", "openEachlabs(this)", "nav.eachlabs"),
            ("apikey-fun", "openApikeyFun(this)", "nav.apikeyFun"),
            ("merge-gateway", "openMergeGateway(this)", "nav.mergeGateway"),
            ("animos", "openAnimos(this)", "nav.animos"),
            ("brand-gen", "openBrandGen(this)", "nav.brandGen"),
            ("adam", "openAdam(this)", "nav.adam"),
            ("cutia", "openCutia(this)", "nav.cutia"),
            ("opencut", "openOpenCut(this)", "nav.opencut"),
            ("motion-dev", "openMotionDev(this)", "nav.motionDev"),
            ("minimax-h3", "openMinimaxH3(this)", "nav.minimaxH3"),
            ("openprocessing", "openOpenProcessing(this)", "nav.openprocessing"),
            ("gen-gestaltung", "openGenGestaltung(this)", "nav.genGestaltung"),
            ("recent-design", "openRecentDesign(this)", "nav.recentDesign"),
            ("codrops-gsap", "openCodropsGsap(this)", "nav.codropsGsap"),
            ("artificial-lab", "openArtificialLab(this)", "nav.artificialLab"),
            ("brik-space", "openBrikSpace(this)", "nav.brikSpace"),
            ("asc11", "openAsc11(this)", "nav.asc11"),
            ("design-arena", "openDesignArena(this)", "nav.designArena"),
            ("snitscanner", "openSnitScanner(this)", "nav.snitScanner"),
            ("spinespine", "openSpineSpine(this)", "nav.spineSpine"),
            ("intr-pattern", "openIntrPattern(this)", "nav.intrPattern"),
            ("tooooools", "openTooooools(this)", "nav.tooooools"),
            ("effect-app", "openEffectApp(this)", "nav.effectApp"),
            ("gianluca-sketches", "openGianlucaSketches(this)", "nav.gianlucaSketches"),
            ("digitiles", "openDigitiles(this)", "nav.digitiles"),
            ("pixelsynth", "openPixelSynth(this)", "nav.pixelSynth"),
            ("fontbox", "openFontBox(this)", "nav.fontBox"),
            ("pixel-perfect", "openPixelPerfect(this)", "nav.pixelPerfect"),
            ("divisare", "openDivisare(this)", "nav.divisare"),
            ("kontextur", "openKontextur(this)", "nav.kontextur"),
            ("gradient-lab", "openGradientLab(this)", "nav.gradientLab"),
            ("bg-freebies", "openBgFreebies(this)", "nav.bgFreebies"),
            ("ascii-magic", "openAsciiMagic(this)", "nav.asciiMagic"),
            ("dotforge", "openDotForge(this)", "nav.dotforge"),
            ("duck-ai", "openDuckAi(this)", "nav.duckAi"),
            ("flux-tools", "openFluxTools(this)", "nav.fluxTools"),
            ("flux-precise", "openFluxPrecise(this)", "nav.fluxPrecise"),
            ("brik-editor", "openBrikEditor(this)", "nav.brikEditor"),
            ("brik-mousegrid", "openBrikMousegrid(this)", "nav.brikMousegrid"),
            ("aholo3d", "openAholo3d(this)", "nav.aholo3d"),
            ("artcraft", "openArtcraft(this)", "nav.artcraft"),
        ]:
            self.assertTrue(f'data-ext-tab="{tab_id}"' in html, f"Missing data-ext-tab='{tab_id}' in index.html")
            self.assertTrue(f'onclick="{onclick_fn}"' in html, f"Missing onclick='{onclick_fn}' in index.html")
            self.assertTrue(f'data-i18n="{i18n_key}"' in html, f"Missing data-i18n='{i18n_key}' in index.html")

        # 4. EXT_TAB_DEFS array entries
        for tab_id in ["feralui", "valessa", "google-pics", "mindvideo", "gen-design", "shadergpt", "sensenova", "fal-ai", "aihubmix", "omniakey", "eachlabs", "apikey-fun", "merge-gateway", "animos", "brand-gen", "adam", "cutia", "opencut", "motion-dev", "minimax-h3", "openprocessing", "gen-gestaltung", "recent-design", "codrops-gsap", "artificial-lab", "brik-space", "asc11", "design-arena", "snitscanner", "spinespine", "intr-pattern", "tooooools", "effect-app", "gianluca-sketches", "digitiles", "pixelsynth", "fontbox", "pixel-perfect", "divisare", "kontextur", "gradient-lab", "bg-freebies", "ascii-magic", "dotforge", "duck-ai", "flux-tools", "flux-precise", "brik-editor", "brik-mousegrid", "aholo3d", "artcraft"]:
            self.assertTrue(f'"{tab_id}",' in html or f"'{tab_id}'," in html, f"Missing {tab_id} in EXT_TAB_DEFS")

        # 5. Window popup functions
        for fn_name in ["openFeralUi", "openValessa", "openGooglePics", "openMindVideo", "openGenDesign", "openShaderGpt", "openSenseNova", "openFalAi", "openAihubmix", "openOmniakey", "openEachlabs", "openApikeyFun", "openMergeGateway", "openAnimos", "openBrandGen", "openAdam", "openCutia", "openOpenCut", "openMotionDev", "openMinimaxH3", "openOpenProcessing", "openGenGestaltung", "openRecentDesign", "openCodropsGsap", "openArtificialLab", "openBrikSpace", "openAsc11", "openDesignArena", "openSnitScanner", "openSpineSpine", "openIntrPattern", "openTooooools", "openEffectApp", "openGianlucaSketches", "openDigitiles", "openPixelSynth", "openFontBox", "openPixelPerfect", "openDivisare", "openKontextur", "openGradientLab", "openBgFreebies", "openAsciiMagic", "openDotForge", "openDuckAi", "openFluxTools", "openFluxPrecise", "openBrikEditor", "openBrikMousegrid", "openAholo3d", "openArtcraft"]:
            self.assertTrue(f'function {fn_name}' in html, f"Missing function {fn_name} in index.html")

        self.assertTrue('https://feralui.dev/gradients' in html, "Missing feralui URL in index.html")
        self.assertTrue('https://valessa.riotters.com/' in html, "Missing valessa URL in index.html")
        self.assertTrue('https://docs.google.com/images/d/1cm3eiOdmL1Z-0ZDrzgWu4MjvxeWEAT05NRWT_dy7keI/edit?pli=1' in html, "Missing google-pics URL in index.html")
        self.assertTrue('https://www.mindvideo.ai/zh/creative-studio/' in html, "Missing mindvideo URL in index.html")
        self.assertTrue('http://www.generative-gestaltung.de/2/' in html, "Missing gen-design URL in index.html")
        self.assertTrue('https://shadergpt.14islands.com/1a1d14d3-9453-449e-be9d-d8477b22d825' in html, "Missing shadergpt URL in index.html")
        self.assertTrue('https://unify.light-ai.top/home?model=u15-lite' in html, "Missing sensenova URL in index.html")
        self.assertTrue('https://fal.ai/dashboard' in html, "Missing fal.ai URL in index.html")
        self.assertTrue('https://aihubmix.com/' in html, "Missing aihubmix URL in index.html")
        self.assertTrue('https://omniakey.com/' in html, "Missing omniakey URL in index.html")
        self.assertTrue('https://eachlabs.ai/' in html or 'https://www.eachlabs.ai/' in html, "Missing eachlabs URL in index.html")
        self.assertTrue('https://apikey.fun/' in html, "Missing apikey.fun URL in index.html")
        self.assertTrue('https://gateway.merge.dev/' in html, "Missing merge-gateway URL in index.html")
        self.assertTrue('https://animos.app/editor' in html, "Missing animos URL in index.html")
        self.assertTrue('https://brand-generator.stoyanov.works/' in html, "Missing brand-gen URL in index.html")
        self.assertTrue('https://adam.new/' in html, "Missing adam URL in index.html")
        self.assertTrue('https://cutia.msgbyte.com/zh' in html, "Missing cutia URL in index.html")
        self.assertTrue('https://opencut.app/' in html, "Missing opencut URL in index.html")
        self.assertTrue('https://motion.dev/' in html, "Missing motion-dev URL in index.html")
        self.assertTrue('https://fal.ai/models/minimax/h3-max/image-to-video' in html, "Missing minimax-h3 URL in index.html")
        self.assertTrue('https://openprocessing.org/' in html, "Missing openprocessing URL in index.html")
        self.assertTrue('http://www.generative-gestaltung.de/' in html, "Missing gen-gestaltung URL in index.html")
        self.assertTrue('https://recent.design' in html, "Missing recent-design URL in index.html")
        self.assertTrue('https://tympanus.net/codrops/hub/tag/gsap/' in html, "Missing codrops-gsap URL in index.html")
        self.assertTrue('https://artificialanalysis.ai/image/image-lab' in html, "Missing artificial-lab URL in index.html")
        self.assertTrue('https://brik.space/gallery' in html, "Missing brik-space URL in index.html")
        self.assertTrue('https://asc11.com/' in html, "Missing asc11 URL in index.html")
        self.assertTrue('https://www.designarena.ai/' in html, "Missing design-arena URL in index.html")
        self.assertTrue('https://snitscanner.xyz/' in html, "Missing snitscanner URL in index.html")
        self.assertTrue('https://www.spinespinespine.tools/' in html, "Missing spinespine URL in index.html")
        self.assertTrue('https://wangxian.work/tools/intr-tools/INTR-PATTERN.html' in html, "Missing intr-pattern URL in index.html")
        self.assertTrue('https://www.tooooools.app/' in html, "Missing tooooools URL in index.html")
        self.assertTrue('https://effect.app/explore' in html, "Missing effect-app URL in index.html")
        self.assertTrue('https://www.gianluca.club/sketches' in html, "Missing gianluca-sketches URL in index.html")
        self.assertTrue('https://eduardadu.github.io/Digitiles/create.html' in html, "Missing digitiles URL in index.html")
        self.assertTrue('https://pixelsynth.com/' in html, "Missing pixelsynth URL in index.html")
        self.assertTrue('https://fontbox.barcoloudly.com/' in html, "Missing fontbox URL in index.html")
        self.assertTrue('https://www.pixel-perfect.space/' in html, "Missing pixel-perfect URL in index.html")
        self.assertTrue('https://www.divisare.com' in html, "Missing divisare URL in index.html")
        self.assertTrue('https://kontextur.info/studiolists' in html, "Missing kontextur URL in index.html")
        self.assertTrue('https://backgrounds.supply/gradient-lab' in html, "Missing gradient-lab URL in index.html")
        self.assertTrue('https://backgrounds.supply/freebies' in html, "Missing bg-freebies URL in index.html")
        self.assertTrue('https://www.ascii-magic.com/' in html, "Missing ascii-magic URL in index.html")
        self.assertTrue('https://dotforge.vercel.app/' in html, "Missing dotforge URL in index.html")
        self.assertTrue('https://duck.ai/' in html, "Missing duck-ai URL in index.html")
        self.assertTrue('https://flux-tools.bfl.ai/' in html, "Missing flux-tools URL in index.html")
        self.assertTrue('https://flux-tools.bfl.ai/precise-editing' in html, "Missing flux-precise URL in index.html")
        self.assertTrue('https://brik.space/tooleditor/6ac799b728cbfe67305e50bf' in html, "Missing brik-editor URL in index.html")
        self.assertTrue('https://brik.space/toolviewer?slug=mousegrid-mo0453fe' in html, "Missing brik-mousegrid URL in index.html")
        self.assertTrue('https://www.aholo3d.cn/' in html, "Missing aholo3d URL in index.html")
        self.assertTrue('https://app.getartcraft.com/' in html, "Missing artcraft URL in index.html")

    def test_api_settings_and_i18n(self):
        self.longMessage = False
        api_settings_path = ROOT / "static" / "js" / "api-settings.js"
        self.assertTrue(api_settings_path.exists(), f"File not found: {api_settings_path}")
        api_content = api_settings_path.read_text(encoding="utf-8")

        all_tools = ["feralui", "valessa", "google-pics", "mindvideo", "gen-design", "shadergpt", "sensenova", "fal-ai", "aihubmix", "omniakey", "eachlabs", "apikey-fun", "merge-gateway", "animos", "brand-gen", "adam", "cutia", "opencut", "motion-dev", "minimax-h3", "openprocessing", "gen-gestaltung", "recent-design", "codrops-gsap", "artificial-lab", "brik-space", "asc11", "design-arena", "snitscanner", "spinespine", "intr-pattern", "tooooools", "effect-app", "gianluca-sketches", "digitiles", "pixelsynth", "fontbox", "pixel-perfect", "divisare", "kontextur", "gradient-lab", "bg-freebies", "ascii-magic", "dotforge", "duck-ai", "flux-tools", "flux-precise", "brik-editor", "brik-mousegrid", "aholo3d", "artcraft"]
        for tid in all_tools:
            self.assertIn(f'id: "{tid}"', api_content, f"Missing {tid} in api-settings.js")

        studio_path = ROOT / "static" / "js" / "i18n" / "studio.js"
        self.assertTrue(studio_path.exists(), f"File not found: {studio_path}")
        studio_content = studio_path.read_text(encoding="utf-8")

        for i18n_k in ["nav.feralui", "nav.valessa", "nav.googlePics", "nav.mindvideo", "nav.genDesign", "nav.shadergpt", "nav.sensenova", "nav.falAi", "nav.aihubmix", "nav.omniakey", "nav.eachlabs", "nav.apikeyFun", "nav.mergeGateway", "nav.animos", "nav.brandGen", "nav.adam", "nav.cutia", "nav.opencut", "nav.motionDev", "nav.minimaxH3", "nav.openprocessing", "nav.genGestaltung", "nav.recentDesign", "nav.codropsGsap", "nav.artificialLab", "nav.brikSpace", "nav.asc11", "nav.designArena", "nav.snitScanner", "nav.spineSpine", "nav.intrPattern", "nav.tooooools", "nav.effectApp", "nav.gianlucaSketches", "nav.digitiles", "nav.pixelSynth", "nav.fontBox", "nav.pixelPerfect", "nav.divisare", "nav.kontextur", "nav.gradientLab", "nav.bgFreebies", "nav.asciiMagic", "nav.dotforge", "nav.duckAi", "nav.fluxTools", "nav.fluxPrecise", "nav.brikEditor", "nav.brikMousegrid", "nav.aholo3d", "nav.artcraft"]:
            self.assertIn(f'"{i18n_k}":', studio_content, f"Missing {i18n_k} in studio.js")

        common_path = ROOT / "static" / "js" / "i18n" / "common.js"
        self.assertTrue(common_path.exists(), f"File not found: {common_path}")
        common_content = common_path.read_text(encoding="utf-8")

        for i18n_k in ["nav.feralui", "nav.valessa", "nav.googlePics", "nav.mindvideo", "nav.genDesign", "nav.shadergpt", "nav.sensenova", "nav.falAi", "nav.aihubmix", "nav.omniakey", "nav.eachlabs", "nav.apikeyFun", "nav.mergeGateway", "nav.animos", "nav.brandGen", "nav.adam", "nav.cutia", "nav.opencut", "nav.motionDev", "nav.minimaxH3", "nav.openprocessing", "nav.genGestaltung", "nav.recentDesign", "nav.codropsGsap", "nav.artificialLab", "nav.brikSpace", "nav.asc11", "nav.designArena", "nav.snitScanner", "nav.spineSpine", "nav.intrPattern", "nav.tooooools", "nav.effectApp", "gianluca-sketches" if False else "nav.gianlucaSketches", "nav.digitiles", "nav.pixelSynth", "nav.fontBox", "nav.pixelPerfect", "nav.divisare", "nav.kontextur", "nav.gradientLab", "nav.bgFreebies", "nav.asciiMagic", "nav.dotforge", "nav.duckAi", "nav.fluxTools", "nav.fluxPrecise", "nav.brikEditor", "nav.brikMousegrid", "nav.aholo3d", "nav.artcraft"]:
            self.assertIn(f'"{i18n_k}":', common_content, f"Missing {i18n_k} in common.js")


    def test_tooltip_markup_and_logic_in_index_html(self):
        html_path = ROOT / "static" / "index.html"
        self.assertTrue(html_path.exists(), f"File not found: {html_path}")
        html = html_path.read_text(encoding="utf-8")
        shell_js = ROOT / "static" / "js" / "studio-shell.js"
        if shell_js.exists():
            html += "\n" + shell_js.read_text(encoding="utf-8")
        shell_css = ROOT / "static" / "css" / "studio-shell.css"
        if shell_css.exists():
            html += "\n" + shell_css.read_text(encoding="utf-8")

        # 1. Check DOM structure for singleton tooltip
        self.assertIn('id="ext-tab-tooltip"', html, "Missing #ext-tab-tooltip singleton container in index.html")
        self.assertIn('class="ext-tab-tooltip"', html, "Missing .ext-tab-tooltip class in index.html")
        self.assertIn('id="ext-tooltip-img"', html, "Missing #ext-tooltip-img in index.html")
        self.assertIn('id="ext-tooltip-badge"', html, "Missing #ext-tooltip-badge in index.html")
        self.assertIn('id="ext-tooltip-title"', html, "Missing #ext-tooltip-title in index.html")
        self.assertIn('id="ext-tooltip-domain"', html, "Missing #ext-tooltip-domain in index.html")
        self.assertIn('id="ext-tooltip-desc"', html, "Missing #ext-tooltip-desc in index.html")

        # 2. Check CSS styles in <style>
        self.assertIn('.ext-tab-tooltip', html, "Missing .ext-tab-tooltip CSS rule in index.html")
        self.assertIn('width: 320px', html, "Missing width: 320px in index.html")
        self.assertIn('aspect-ratio: 16 / 9', html, "Missing 16:9 aspect ratio in index.html")
        self.assertIn('ext-tooltip-media', html, "Missing .ext-tooltip-media in index.html")

        # 3. Check initExtTabTooltips logic
        self.assertIn('function initExtTabTooltips', html, "Missing initExtTabTooltips function in index.html")
        self.assertIn('initExtTabTooltips()', html, "Missing call to initExtTabTooltips() in index.html")
        self.assertIn('ext-folder-body', html, "Missing ext-folder-body listener in index.html")

    def test_search_and_category_filter_in_index_html(self):
        html_path = ROOT / "static" / "index.html"
        self.assertTrue(html_path.exists(), f"File not found: {html_path}")
        html = html_path.read_text(encoding="utf-8")
        shell_js = ROOT / "static" / "js" / "studio-shell.js"
        if shell_js.exists():
            html += "\n" + shell_js.read_text(encoding="utf-8")
        shell_css = ROOT / "static" / "css" / "studio-shell.css"
        if shell_css.exists():
            html += "\n" + shell_css.read_text(encoding="utf-8")

        # Check search markup & scripts
        self.assertIn('id="ext-search-input"', html)
        self.assertIn('handleExtSearch', html)
        self.assertIn('clearExtSearch', html)

        # Check category filter markup & scripts
        self.assertIn('id="ext-cat-pills"', html)
        self.assertIn('setExtCategory', html)
        self.assertIn('data-cat="AI 生图与设计"', html)
        self.assertIn('data-cat="视频与动效"', html)
        self.assertIn('data-cat="建筑与空间灵感"', html)
        self.assertIn('data-cat="创意编程与实验"', html)
        self.assertIn('data-cat="大模型与评测"', html)
        self.assertIn('data-cat="工作流与 API"', html)

        # Check count & empty states
        self.assertIn('id="ext-filter-count-text"', html)
        self.assertIn('id="ext-empty-state"', html)
        self.assertIn('applyExtFolderFilters', html)
        self.assertIn('toggleAllExtCategories', html)


if __name__ == "__main__":
    unittest.main()

