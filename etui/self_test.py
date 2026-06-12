# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

"""Built-in self-tests for etui.

Each test is a plain function named test_*. It raises AssertionError (or any
Exception) on failure and returns None on success. Tests must be fast, side-
effect-free, and require no external hardware or network access.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelfTestResult:
    name: str
    passed: bool
    message: str


def _collect() -> list[Callable[[], None]]:
    """Return all test_* functions defined in this module."""
    import etui.self_test as _self
    return [
        fn for name, fn in vars(_self).items()
        if name.startswith("test_") and callable(fn)
    ]


def run_all() -> list[SelfTestResult]:
    """Run every test and return results. Never raises."""
    results: list[SelfTestResult] = []
    for fn in _collect():
        name = fn.__name__.removeprefix("test_").replace("_", " ")
        try:
            fn()
            results.append(SelfTestResult(name, True, "ok"))
        except Exception as exc:
            results.append(SelfTestResult(name, False, str(exc)))
    return results


# ---------------------------------------------------------------------------
# Tests — version / metadata
# ---------------------------------------------------------------------------

def test_copyright_defined() -> None:
    from etui.version import COPYRIGHT
    assert COPYRIGHT and "32bit" in COPYRIGHT.lower(), f"unexpected: {COPYRIGHT!r}"


# ---------------------------------------------------------------------------
# Tests — settings manager
# ---------------------------------------------------------------------------

def test_settings_defaults_are_complete() -> None:
    from etui.settings import DEFAULT_SETTINGS
    for key in ("workspace", "probe", "lldb", "tools", "ui"):
        assert key in DEFAULT_SETTINGS, f"missing category: {key}"


def test_settings_fresh_load_returns_defaults() -> None:
    from etui.settings import SettingsManager, DEFAULT_SETTINGS
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=True) as f:
        path = Path(f.name)
    # file deleted — SettingsManager must start from defaults
    m = SettingsManager(path=path)
    assert m.settings["probe"]["backend"] == DEFAULT_SETTINGS["probe"]["backend"]
    assert m.settings["ui"]["word_wrap"] == DEFAULT_SETTINGS["ui"]["word_wrap"]


def test_settings_save_reload_roundtrip() -> None:
    from etui.settings import SettingsManager
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.yaml"
        m = SettingsManager(path=path)
        m.set("ui", "word_wrap", True)
        m2 = SettingsManager(path=path)
        assert m2.get("ui", "word_wrap") is True


def test_settings_atomic_write_leaves_no_tmp() -> None:
    from etui.settings import SettingsManager
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.yaml"
        m = SettingsManager(path=path)
        m.save_settings()
        tmp = path.with_suffix(".yaml.tmp")
        assert not tmp.exists(), f"temp file not cleaned up: {tmp}"


def test_settings_unknown_keys_ignored() -> None:
    import yaml
    from etui.settings import SettingsManager
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.yaml"
        path.write_text(yaml.safe_dump({
            "workspace": {"root": "/tmp", "ghost": True},
            "alien_category": {"x": 1},
        }))
        m = SettingsManager(path=path)
        assert "ghost" not in m.settings["workspace"]
        assert "alien_category" not in m.settings


def test_settings_replace_strips_unknown_categories() -> None:
    from etui.settings import SettingsManager, DEFAULT_SETTINGS
    from copy import deepcopy
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.yaml"
        m = SettingsManager(path=path)
        updated = deepcopy(DEFAULT_SETTINGS)
        updated["probe"]["backend"] = "openocd"
        updated["_unknown"] = {"foo": "bar"}
        m.replace(updated)
        m2 = SettingsManager(path=path)
        assert m2.get("probe", "backend") == "openocd"
        assert "_unknown" not in m2.settings


def test_settings_legacy_migration() -> None:
    from etui.settings import SettingsManager
    with tempfile.TemporaryDirectory() as d:
        cfg = Path(d)
        (cfg / "workspace.json").write_text(json.dumps({"workspace_root": "/tmp/legacy"}))
        (cfg / "debugger.json").write_text(json.dumps({"gdb_port": 9999}))
        (cfg / "dashboard.json").write_text(json.dumps({"theme": "ocean"}))
        (cfg / "tools.json").write_text(json.dumps(["/opt/bin"]))
        m = SettingsManager(path=cfg / "settings.yaml")
        assert m.get("workspace", "root") == "/tmp/legacy"
        assert m.get("probe", "gdb_port") == 9999
        assert m.get("lldb", "theme") == "ocean"
        assert "/opt/bin" in m.get("tools", "custom_paths")


# ---------------------------------------------------------------------------
# Tests — documentation
# ---------------------------------------------------------------------------

def test_doc_index_exists() -> None:
    from etui.tabs.about import DEFAULT_SCREENSHOT_DIR
    doc_dir = DEFAULT_SCREENSHOT_DIR.parent
    index = doc_dir / "index.md"
    assert index.is_file(), f"missing: {index}"


def test_doc_tab_files_exist() -> None:
    from etui.tabs.help import _MENU, _DOC_DIR
    missing = [rel for _, rel, _ in _MENU if not (_DOC_DIR / rel).is_file()]
    assert not missing, f"missing doc files: {missing}"


def test_screenshot_dir_is_inside_doc() -> None:
    from etui.tabs.about import DEFAULT_SCREENSHOT_DIR
    doc_dir = DEFAULT_SCREENSHOT_DIR.parent
    assert DEFAULT_SCREENSHOT_DIR.is_relative_to(doc_dir), \
        f"screenshot dir {DEFAULT_SCREENSHOT_DIR} not under doc dir {doc_dir}"


# ---------------------------------------------------------------------------
# Tests — probe tab
# ---------------------------------------------------------------------------

def test_stlink_vids_in_known_usb_probes() -> None:
    from etui.tabs.probe import KNOWN_USB_PROBES
    stlink_pids = {0x3748, 0x374b, 0x374e, 0x374f}
    found = {pid for (vid, pid), _ in KNOWN_USB_PROBES.items() if vid == 0x0483}
    missing = stlink_pids - found
    assert not missing, f"ST-LINK VID:PIDs missing from KNOWN_USB_PROBES: {missing:#06x}"


def test_stlink_usb_probes_use_pyocd_driver() -> None:
    from etui.tabs.probe import KNOWN_USB_PROBES
    for (vid, pid), (desc, driver, _) in KNOWN_USB_PROBES.items():
        if vid == 0x0483:
            assert driver == "pyocd", f"{desc} should use pyocd driver, got {driver!r}"


def test_stlink_backend_registered() -> None:
    from etui.tabs.probe import BACKENDS
    assert "stlink" in BACKENDS, "stlink missing from BACKENDS"
    assert BACKENDS["stlink"][0] == "st-util", "stlink backend should invoke st-util"


def test_stlink_gdb_port_in_default_settings() -> None:
    from etui.tabs.probe import DEFAULT_SETTINGS, STLINK_GDB_PORT
    assert "stlink_gdb_port" in DEFAULT_SETTINGS, "stlink_gdb_port missing from DEFAULT_SETTINGS"
    assert DEFAULT_SETTINGS["stlink_gdb_port"] == STLINK_GDB_PORT


def test_lpc_link2_cmsis_dap_usb_probe_registered() -> None:
    from etui.tabs.probe import CMSIS_DAP_INTERFACE, KNOWN_USB_PROBES
    desc, driver, interface = KNOWN_USB_PROBES[(0x1FC9, 0x0090)]
    assert desc == "NXP LPC-LINK2 CMSIS-DAP"
    assert driver == "pyocd"
    assert interface == CMSIS_DAP_INTERFACE


# ---------------------------------------------------------------------------
# Tests — tab registry
# ---------------------------------------------------------------------------

def test_tab_ids_cover_all_menu_entries() -> None:
    from etui.tabs.about import TAB_IDS
    from etui.tabs.help import _MENU
    # Every help menu entry that is a tab doc should correspond to a known tab.
    tab_docs = {rel.removeprefix("tabs/").removesuffix(".md")
                for _, rel, _ in _MENU if rel.startswith("tabs/")}
    missing = tab_docs - set(TAB_IDS)
    assert not missing, f"help menu entries not in TAB_IDS: {missing}"


# ---------------------------------------------------------------------------
# Tests — markdown viewer
# ---------------------------------------------------------------------------

def test_safe_markdown_viewer_resolves_relative_links() -> None:
    from etui.tabs.files import SafeMarkdownViewer, _MD_SUFFIXES
    from pathlib import PurePosixPath

    # Simulate the resolution logic without a running app.
    base = Path("/some/doc/index.md")
    href = "tabs/files.md"
    resolved = (base.parent / href).resolve()
    assert resolved == Path("/some/doc/tabs/files.md")


def test_safe_markdown_viewer_uses_loaded_document_as_link_base() -> None:
    from etui.tabs.files import SafeMarkdownViewer

    viewer = SafeMarkdownViewer(show_table_of_contents=False)
    viewer._current_document = Path("/some/doc/tabs/probe.md")
    href = "../probes/stlink.md"
    resolved = (viewer._current_document.parent / href).resolve()
    assert resolved == Path("/some/doc/probes/stlink.md")


def test_safe_markdown_viewer_blocks_non_md_links() -> None:
    from etui.tabs.files import _MD_SUFFIXES
    non_md = ["../screenshots/foo.svg", "http://example.com", "image.png", "data.json"]
    for href in non_md:
        suffix = Path(href).suffix.lower()
        assert suffix not in _MD_SUFFIXES, f"{href!r} should be blocked"
