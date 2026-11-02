"""Offline tests: no user config, internet, API credentials or AI quota."""
import unittest
from main import canonical_api_base, resolve_probe_key, UntrustedProbeTarget


class ProviderProbeKeySecurityTests(unittest.TestCase):
    def setUp(self):
        self.providers = [{"id": "demo", "base_url": "https://api.example.com/v1", "enabled": True}]
        self.calls = []

    def read_key(self, provider_id):
        self.calls.append(provider_id)
        return "test-only-stored-key"

    def key(self, url, *, explicit="", provider_id="demo"):
        return resolve_probe_key(explicit, url, provider_id, self.providers, self.read_key)

    def test_matching_saved_provider_can_use_saved_key(self):
        self.assertEqual(self.key("HTTPS://API.EXAMPLE.COM:443/v1/"), "test-only-stored-key")
        self.assertEqual(self.calls, ["demo"])

    def test_changed_host_cannot_exfiltrate_saved_key(self):
        with self.assertRaises(UntrustedProbeTarget):
            self.key("https://api.example.com.attacker.test/v1")
        self.assertEqual(self.calls, [])

    def test_changed_scheme_port_or_path_cannot_reuse_saved_key(self):
        for url in ["http://api.example.com/v1", "https://api.example.com:8443/v1", "https://api.example.com/v2", "https://attacker.test/v1"]:
            with self.subTest(url=url), self.assertRaises(UntrustedProbeTarget):
                self.key(url)
        self.assertEqual(self.calls, [])

    def test_temporary_explicit_key_can_probe_new_url_without_reading_saved_key(self):
        self.assertEqual(self.key("https://new.example.com/v1", explicit="test-only-temporary-key"), "test-only-temporary-key")
        self.assertEqual(self.calls, [])

    def test_no_provider_id_cannot_load_global_fallback_key(self):
        self.assertEqual(self.key("https://example.com", provider_id=""), "")
        self.assertEqual(self.calls, [])

    def test_unknown_or_disabled_provider_does_not_load_key(self):
        self.assertEqual(self.key("https://api.example.com/v1", provider_id="unknown"), "")
        self.providers[0]["enabled"] = False
        self.assertEqual(self.key("https://api.example.com/v1"), "")
        self.assertEqual(self.calls, [])

    def test_unicode_idna_alias_cannot_reuse_ascii_saved_key(self):
        self.providers[0]["base_url"] = "https://fass.example/v1"
        for url in ["https://faß.example/v1", "https://fass.example/v1"]:
            with self.subTest(url=url):
                if "faß" in url:
                    with self.assertRaises(UntrustedProbeTarget):
                        self.key(url)
                else:
                    self.assertEqual(self.key(url), "test-only-stored-key")

    def test_punycode_ascii_is_not_equal_to_unicode_alias(self):
        self.providers[0]["base_url"] = "https://xn--fa-hia.example/v1"
        with self.assertRaises(UntrustedProbeTarget):
            self.key("https://faß.example/v1")
        self.assertEqual(self.key("https://xn--fa-hia.example/v1"), "test-only-stored-key")

    def test_reject_credentials_queries_and_fragments(self):
        for url in ["https://user:pass@api.example.com/v1", "https://api.example.com/v1?q=1", "https://api.example.com/v1#frag", "https://api.example.com:0/v1", "https://api.example.com/v1\\nmalicious".replace("\\n", "\n")]:
            with self.subTest(url=url), self.assertRaises(UntrustedProbeTarget):
                self.key(url)
        self.assertEqual(self.calls, [])

    def test_normalizer_blocks_invalid_base(self):
        for url in ["", "file:///etc/passwd", "https://host/?x=1", "https://host#frag", "https://user@host", "https://host:65536", "https://host:0", "https://host/a b", "https://faß.example/v1"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_api_base(url)


if __name__ == "__main__":
    unittest.main()
