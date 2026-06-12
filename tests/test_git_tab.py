# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import unittest
from etui.tabs.git import GitTab, GitChange

class GitTabUnitTests(unittest.TestCase):
    def test_parse_porcelain_v2_untracked(self) -> None:
        tab = GitTab()
        raw = b"? file_untracked.txt\x00"
        staged, unstaged = tab._parse_porcelain_v2(raw)
        self.assertEqual(len(staged), 0)
        self.assertEqual(len(unstaged), 1)
        self.assertEqual(unstaged[0].path, "file_untracked.txt")
        self.assertEqual(unstaged[0].status, "?")
        self.assertFalse(unstaged[0].staged)

    def test_parse_porcelain_v2_modified(self) -> None:
        tab = GitTab()
        # xy = 'M.' (staged modified) or '.M' (unstaged modified)
        raw = b"1 M. N... 100644 100644 100644 1234567890abcdef1234567890abcdef12345678 1234567890abcdef1234567890abcdef12345678 file_staged.txt\x00"
        staged, unstaged = tab._parse_porcelain_v2(raw)
        self.assertEqual(len(staged), 1)
        self.assertEqual(len(unstaged), 0)
        self.assertEqual(staged[0].path, "file_staged.txt")
        self.assertEqual(staged[0].status, "M")
        self.assertTrue(staged[0].staged)

    def test_parse_porcelain_v2_rename(self) -> None:
        tab = GitTab()
        raw = b"2 R. N... 100644 100644 100644 1234567890abcdef1234567890abcdef12345678 1234567890abcdef1234567890abcdef12345678 R100 new_path.txt\x00old_path.txt\x00"
        staged, unstaged = tab._parse_porcelain_v2(raw)
        self.assertEqual(len(staged), 1)
        self.assertEqual(len(unstaged), 0)
        self.assertEqual(staged[0].path, "new_path.txt")
        self.assertEqual(staged[0].status, "R")
        self.assertTrue(staged[0].staged)

    def test_parse_porcelain_v2_unmerged(self) -> None:
        tab = GitTab()
        raw = b"u UU N... 100644 100644 100644 100644 1234567890abcdef1234567890abcdef12345678 1234567890abcdef1234567890abcdef12345678 1234567890abcdef1234567890abcdef12345678 conflicted.txt\x00"
        staged, unstaged = tab._parse_porcelain_v2(raw)
        # UU means staged is U, unstaged is U
        self.assertEqual(len(staged), 1)
        self.assertEqual(len(unstaged), 1)
        self.assertEqual(staged[0].path, "conflicted.txt")
        self.assertEqual(staged[0].status, "U")
        self.assertTrue(staged[0].staged)
        self.assertEqual(unstaged[0].path, "conflicted.txt")
        self.assertEqual(unstaged[0].status, "U")
        self.assertFalse(unstaged[0].staged)

if __name__ == "__main__":
    unittest.main()
