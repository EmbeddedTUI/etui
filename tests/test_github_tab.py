# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import unittest
from etui.tabs.github import GitHubTab

class GitHubTabUnitTests(unittest.TestCase):
    def test_parse_github_remote_https(self) -> None:
        lines = [
            "origin\thttps://github.com/32bitmicroLLC/EmbeddedTUI.git (fetch)",
            "origin\thttps://github.com/32bitmicroLLC/EmbeddedTUI.git (push)",
        ]
        slug = GitHubTab.parse_github_remote(lines)
        self.assertEqual(slug, "32bitmicroLLC/EmbeddedTUI")

    def test_parse_github_remote_ssh(self) -> None:
        lines = [
            "origin\tgit@github.com:32bitmicroLLC/EmbeddedTUI.git (fetch)",
            "origin\tgit@github.com:32bitmicroLLC/EmbeddedTUI.git (push)",
        ]
        slug = GitHubTab.parse_github_remote(lines)
        self.assertEqual(slug, "32bitmicroLLC/EmbeddedTUI")

    def test_parse_github_remote_ssh_alt(self) -> None:
        lines = [
            "origin\tgit@ssh.github.com:32bitmicroLLC/EmbeddedTUI.git (fetch)",
        ]
        slug = GitHubTab.parse_github_remote(lines)
        self.assertEqual(slug, "32bitmicroLLC/EmbeddedTUI")

    def test_parse_github_remote_invalid_host(self) -> None:
        lines = [
            "origin\tgit@evilgithub.com:32bitmicroLLC/EmbeddedTUI.git (fetch)",
        ]
        slug = GitHubTab.parse_github_remote(lines)
        self.assertIsNone(slug)

    def test_parse_github_remote_priority(self) -> None:
        lines = [
            "origin\tgit@github.com:someuser/somerepo.git (fetch)",
            "upstream\tgit@github.com:32bitmicroLLC/EmbeddedTUI.git (fetch)",
        ]
        slug = GitHubTab.parse_github_remote(lines)
        # upstream should take priority over origin
        self.assertEqual(slug, "32bitmicroLLC/EmbeddedTUI")

    def test_validate_text_safe(self) -> None:
        self.assertEqual(GitHubTab._validate_text("  Valid Title  ", "title"), "Valid Title")

    def test_validate_text_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            GitHubTab._validate_text("   ", "title")

    def test_validate_text_rejects_option_prefix(self) -> None:
        with self.assertRaises(ValueError):
            GitHubTab._validate_text("--invalid-arg", "title")

if __name__ == "__main__":
    unittest.main()
