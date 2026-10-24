import asyncio
import os
import sys
from playwright.async_api import async_playwright
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "images", "ext-previews")
os.makedirs(OUT_DIR, exist_ok=True)

TOOLS = [
    ("mai", "https://playground.microsoft.ai/"),
    ("copilot", "https://copilot.microsoft.com/imagine"),
    ("arena", "https://arena.ai/"),
    ("reve", "https://reve.com/"),
    ("gflow", "https://labs.google/fx/zh/tools/flow"),
    ("grok", "https://grok.com/imagine"),
    ("qianwen", "https://create.qianwen.com/"),
    ("chatgpt", "https://chatgpt.com/"),
    ("rh-canvas", "https://rhtv.runninghub.cn/"),
    ("rh-user", "https://runninghub.cn/"),
    ("cloudcb", "https://cloudcb.me/"),
    ("ascii", "https://asciiflow.com/"),
    ("ladybug", "https://app.theladybug.app/"),
    ("boardmix", "https://boardmix.cn/"),
    ("canva", "https://canva.com/"),
    ("longcat", "https://longcat.chat/"),
    ("dola", "https://dola.com/"),
    ("agnes-wb", "https://agnes-image-gen.netlify.app/"),
    ("lovart", "https://lovart.ai/"),
    ("topaz", "https://topazlabs.com/"),
    ("tooootem", "https://tooootem.vercel.app/"),
    ("feralui", "https://feralui.dev/gradients"),
    ("valessa", "https://valessa.riotters.com/"),
    ("google-pics", "https://docs.google.com/images/d/1cm3eiOdmL1Z-0ZDrzgWu4MjvxeWEAT05NRWT_dy7keI/edit?pli=1"),
    ("mindvideo", "https://www.mindvideo.ai/zh/creative-studio/"),
    ("gen-design", "http://www.generative-gestaltung.de/2/"),
    ("shadergpt", "https://shadergpt.14islands.com/1a1d14d3-9453-449e-be9d-d8477b22d825"),
    ("sensenova", "https://unify.light-ai.top/home?model=u15-lite"),
    ("fal-ai", "https://fal.ai/dashboard"),
    ("aihubmix", "https://aihubmix.com/"),
    ("omniakey", "https://omniakey.com/"),
    ("eachlabs", "https://www.eachlabs.ai/"),
    ("apikey-fun", "https://apikey.fun/"),
    ("merge-gateway", "https://gateway.merge.dev/"),
    ("animos", "https://animos.app/editor"),
    ("brand-gen", "https://brand-generator.stoyanov.works/"),
    ("adam", "https://adam.new/"),
    ("cutia", "https://cutia.msgbyte.com/zh"),
    ("opencut", "https://opencut.app/"),
    ("motion-dev", "https://motion.dev/"),
    ("minimax-h3", "https://fal.ai/models/minimax/h3-max/image-to-video"),
    ("openprocessing", "https://openprocessing.org/"),
    ("gen-gestaltung", "http://www.generative-gestaltung.de/"),
    ("recent-design", "https://recent.design"),
]


async def capture_all():
    print(f"Starting real screenshot capture for {len(TOOLS)} external tools...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )

        success_count = 0
        fail_count = 0

        for idx, (tid, url) in enumerate(TOOLS, 1):
            out_path = os.path.join(OUT_DIR, f"{tid}.png")
            print(f"[{idx}/{len(TOOLS)}] Capturing {tid}: {url} ...")
            page = await context.new_page()
            try:
                await page.goto(url, timeout=18000, wait_until="domcontentloaded")
                await asyncio.sleep(3.0)

                temp_path = os.path.join(OUT_DIR, f"temp_{tid}.png")
                await page.screenshot(path=temp_path, full_page=False)

                with Image.open(temp_path) as img:
                    img_rgb = img.convert("RGB")
                    target_w, target_h = 1200, 675
                    resized = img_rgb.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    resized.save(out_path, "PNG", optimize=True)

                if os.path.exists(temp_path):
                    os.remove(temp_path)

                file_size = os.path.getsize(out_path)
                print(f"  -> SUCCESS: {tid}.png ({file_size // 1024} KB)")
                success_count += 1
            except Exception as exc:
                print(f"  -> FAILED: {tid} ({exc})")
                fail_count += 1
            finally:
                await page.close()

        await browser.close()
        print(f"\nCapture summary: {success_count} succeeded, {fail_count} failed.")

if __name__ == "__main__":
    asyncio.run(capture_all())
