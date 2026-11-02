"""update_service 单测（GitHub 检查更新 + 仓库配置 config/update.json，set_root 隔离 + 假 HTTP）。"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import bridge.update_service as us  # noqa: E402


class _IsolatedTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        us.set_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_http(self, releases_by_repo):
        """monkeypatch us._http_get_json：按 repo 返回 Release dict；404 仓库抛 HTTPError。"""
        def fake(url, timeout=15):
            repo = url.split("/repos/")[1].rsplit("/releases", 1)[0]
            if repo not in releases_by_repo:
                raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
            return releases_by_repo[repo]
        orig = us._http_get_json
        us._http_get_json = fake
        self.addCleanup(setattr, us, "_http_get_json", orig)


class RepoConfigTest(_IsolatedTestCase):
    def test_default_empty(self):
        self.assertEqual(us.get_repo(), "")

    def test_save_roundtrip(self):
        us.save_repo("owner/repo")
        self.assertEqual(us.get_repo(), "owner/repo")
        with open(os.path.join(self._tmp.name, "config", "update.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"repo": "owner/repo"})

    def test_save_clears_with_empty(self):
        us.save_repo("owner/repo")
        us.save_repo("   ")
        self.assertEqual(us.get_repo(), "")

    def test_invalid_format_rejected(self):
        for bad in ["not-a-repo", "a/b/c", "owner/名称", "/repo", "owner/"]:
            with self.assertRaises(us.UpdateError, msg=bad):
                us.save_repo(bad)

    def test_valid_formats(self):
        for good in ["owner/repo", "owner.v2/repo-x", "a_b/c_d"]:
            us.save_repo(good)
            self.assertEqual(us.get_repo(), good)

    def test_corrupt_file_raises(self):
        cfg = os.path.join(self._tmp.name, "config")
        os.makedirs(cfg, exist_ok=True)
        with open(os.path.join(cfg, "update.json"), "w", encoding="utf-8") as f:
            f.write("{broken")
        with self.assertRaises(us.UpdateError) as cm:
            us.get_repo()
        self.assertEqual(cm.exception.code, "UPDATE_CONFIG_CORRUPT")


class CheckUpdateTest(_IsolatedTestCase):
    def test_newer_release_has_update(self):
        # “更新”标签相对 APP_VERSION 动态生成（版本升级后测试不失效）
        import re as _re
        nums = _re.findall(r"\d+", us.APP_VERSION) or ["0", "0", "0"]
        parts = nums + ["0"] * (3 - len(nums))
        newer = "v" + ".".join(parts[:2] + [str(int(parts[2]) + 1)])
        self._fake_http({"owner/repo": {"tag_name": newer, "name": newer.lstrip("v"),
                                         "html_url": f"https://github.com/owner/repo/releases/tag/{newer}",
                                         "published_at": "2026-11-02T00:00:00Z"}})
        r = us.check_update("owner/repo")
        self.assertTrue(r["has_update"])
        self.assertEqual(r["latest_version"], newer)
        self.assertEqual(r["local_version"], us.APP_VERSION)
        self.assertEqual(r["repo_url"], "https://github.com/owner/repo")

    def test_older_release_no_update(self):
        self._fake_http({"owner/repo": {"tag_name": "v1.1.1"}})
        self.assertFalse(us.check_update("owner/repo")["has_update"])

    def test_equal_release_no_update(self):
        self._fake_http({"owner/repo": {"tag_name": "v" + us.APP_VERSION}})
        self.assertFalse(us.check_update("owner/repo")["has_update"])

    def test_unparseable_tag_no_crash(self):
        self._fake_http({"owner/repo": {"tag_name": "weird-label"}})
        r = us.check_update("owner/repo")
        self.assertFalse(r["has_update"])
        self.assertEqual(r["latest_version"], "weird-label")

    def test_repo_required(self):
        with self.assertRaises(us.UpdateError) as cm:
            us.check_update("")
        self.assertEqual(cm.exception.code, "UPDATE_NO_REPO")

    def test_404_gives_fetch_error(self):
        self._fake_http({})  # 仓库不在表里 → 404
        with self.assertRaises(us.UpdateError) as cm:
            us.check_update("ghost/repo")
        self.assertEqual(cm.exception.code, "UPDATE_FETCH_FAILED")
        self.assertIn("Release", cm.exception.message)

    def test_network_error_gives_fetch_error(self):
        def broken(url, timeout=15):
            raise urllib.error.URLError("connection refused")
        us._http_get_json = broken
        with self.assertRaises(us.UpdateError) as cm:
            us.check_update("owner/repo")
        self.assertEqual(cm.exception.code, "UPDATE_FETCH_FAILED")


if __name__ == "__main__":
    unittest.main()
