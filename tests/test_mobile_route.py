# test_mobile_route.py — 移动端改图页路由行为（unittest 风格，随 117 项套件跑）
# R7 规范：无网络依赖、无 pydantic、无 print 卫生问题
import unittest

MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
DESKTOP_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"


def _client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)


class MobileRouteTests(unittest.TestCase):
    """UA 检测 → mobile.html；?desktop=1 cookie 逃生舱；prefer_desktop cookie 覆盖 UA 重定向"""

    @classmethod
    def setUpClass(cls):
        cls.client = _client()

    def test_mobile_ua_redirected_to_mobile_page(self):
        res = self.client.get("/", headers={"user-agent": MOBILE_UA}, follow_redirects=False)
        self.assertIn(res.status_code, (301, 302, 307, 308))
        self.assertEqual(res.headers["location"], "/static/mobile.html")

    def test_desktop_ua_serves_index(self):
        res = self.client.get("/", headers={"user-agent": DESKTOP_UA})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"<html", res.content[:2000].lower())

    def test_mobile_ua_with_desktop_query_param_gets_index_and_cookie(self):
        res = self.client.get("/?desktop=1", headers={"user-agent": MOBILE_UA})
        self.assertEqual(res.status_code, 200)
        self.assertIn("prefer_desktop", res.headers.get("set-cookie", ""))

    def test_prefer_desktop_cookie_overrides_mobile_ua(self):
        client = _client()
        client.cookies.set("prefer_desktop", "1")
        res = client.get("/", headers={"user-agent": MOBILE_UA})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"<html", res.content[:2000].lower())

    def test_mobile_page_exists(self):
        res = self.client.get("/static/mobile.html")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"mobile.js", res.content)


if __name__ == "__main__":
    unittest.main()
