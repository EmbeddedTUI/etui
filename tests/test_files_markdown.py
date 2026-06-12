# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from textual.widgets import MarkdownViewer

from etui.tabs.files import SafeMarkdownViewer


class MarkdownViewerLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_relative_probe_guide_link_uses_loaded_document_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            doc_dir = Path(directory) / "doc"
            source = doc_dir / "tabs" / "probe.md"
            target = doc_dir / "probes" / "stlink.md"
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_text("[ST-LINK](../probes/stlink.md)")
            target.write_text("# ST-LINK")

            viewer = SafeMarkdownViewer(show_table_of_contents=False)
            parent_go = AsyncMock()
            with patch.object(MarkdownViewer, "go", new=parent_go):
                await viewer.go(source)
                await viewer.go("../probes/stlink.md")

            self.assertEqual(viewer._current_document, target.resolve())
            self.assertEqual(parent_go.await_count, 2)
            self.assertEqual(parent_go.await_args_list[0].args[0], source.resolve())
            self.assertEqual(parent_go.await_args_list[1].args[0], target.resolve())
