# Copyright (c) 2026 Pawel Wodnicki
# Copyright (c) 2026 32bitmico LLC

import tempfile
import asyncio
import unittest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from etui_tools.tab import ToolService, ToolsTab, ToolDefinition, ExecutableProbe, ToolResult, ToolState, ExecutableResult

class ToolsTabUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_package_manager_detection_and_command_building(self) -> None:
        service = ToolService(tuple())
        
        # Define mock tool
        def_tool = ToolDefinition(
            tool_id="mock-tool",
            display_name="Mock Tool",
            probes=(ExecutableProbe("mock_exe", ("--version",)),),
            documentation_url="http://mock",
            package_plans={
                "apt": {"manager": "apt-get", "packages": ("mock-pkg",), "documentation_url": "http://mock"}
            }
        )
        
        # Build command plan
        # We manually inject the package plan as a PackagePlan subclass or dictionary
        from etui_tools.tab import PackagePlan
        def_tool = ToolDefinition(
            tool_id="mock-tool",
            display_name="Mock Tool",
            probes=(ExecutableProbe("mock_exe", ("--version",)),),
            documentation_url="http://mock",
            package_plans={
                "apt": PackagePlan("apt-get", ("mock-pkg",), "http://mock")
            }
        )
        
        cmd = service.build_install_command(def_tool, "apt-get")
        self.assertEqual(cmd, ["apt-get", "install", "-y", "--", "mock-pkg"])

    async def test_find_executable_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            path1 = Path(tmp1)
            path2 = Path(tmp2)
            
            # Create executable stub in path1
            exe1 = path1 / "my_exe"
            exe1.touch()
            exe1.chmod(0o755)
            
            # Create executable stub in path2
            exe2 = path2 / "my_exe"
            exe2.touch()
            exe2.chmod(0o755)
            
            # Search with path1 taking precedence
            service = ToolService((path1, path2))
            res = service.find_executable("my_exe")
            self.assertEqual(res, exe1.resolve())
            
            # Search with path2 taking precedence
            service = ToolService((path2, path1))
            res = service.find_executable("my_exe")
            self.assertEqual(res, exe2.resolve())

    async def test_validate_gnu_arm_target_success(self) -> None:
        service = ToolService(tuple())
        service._capture_command = AsyncMock(return_code=0)
        
        # Mock create_subprocess_exec call
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"arm-none-eabi\n", b""))
        
        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            err = await service.validate_gnu_arm(Path("/usr/bin/gcc"))
            self.assertIsNone(err)

    async def test_validate_gnu_arm_target_mismatch(self) -> None:
        service = ToolService(tuple())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"x86_64-pc-linux-gnu\n", b""))
        
        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            err = await service.validate_gnu_arm(Path("/usr/bin/gcc"))
            self.assertIn("Invalid target machine: x86_64-pc-linux-gnu", err)

    async def test_validate_llvm_arm_success(self) -> None:
        service = ToolService(tuple())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        
        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            err = await service.validate_llvm_arm(Path("/usr/bin/clang"))
            self.assertIsNone(err)

    async def test_validate_llvm_arm_failure(self) -> None:
        service = ToolService(tuple())
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error: unknown target triple 'arm-none-eabi'\n"))
        
        with unittest.mock.patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            err = await service.validate_llvm_arm(Path("/usr/bin/clang"))
            self.assertIn("Target compilation check failed", err)

    def test_tool_registry_and_warning_banner(self) -> None:
        from etui_tools.tab import ToolRegistry, TOOL_BY_ID
        from etui.plugin import ToolWarningBanner
        
        # Mock application object
        app = MagicMock()
        registry = ToolRegistry(app)
        app.tool_registry = registry
        
        # Test default fallback when registry is empty (assuming e.g. "git" is installed on system)
        import shutil
        git_missing_on_path = shutil.which("git") is None
        self.assertEqual(registry.is_missing_or_incomplete("git"), git_missing_on_path)
        
        # Inject tool results
        mock_definition = TOOL_BY_ID["git"]
        installed_result = ToolResult(
            definition=mock_definition,
            state=ToolState.INSTALLED,
            executables=(ExecutableResult("git", "/usr/bin/git", "git version 2.40", None),)
        )
        registry.update_result("git", installed_result)
        self.assertTrue(registry.is_installed("git"))
        self.assertFalse(registry.is_missing_or_incomplete("git"))
        
        missing_result = ToolResult(
            definition=mock_definition,
            state=ToolState.MISSING,
            executables=(ExecutableResult("git", None, None, "Executable not found"),)
        )
        registry.update_result("git", missing_result)
        self.assertFalse(registry.is_installed("git"))
        self.assertTrue(registry.is_missing_or_incomplete("git"))
        
        # Test ToolWarningBanner behavior
        with unittest.mock.patch.object(ToolWarningBanner, "app", new_callable=unittest.mock.PropertyMock) as mock_app:
            mock_app.return_value = app
            banner = ToolWarningBanner("git", "Git")
            import asyncio
            asyncio.run(banner._update_status())
            self.assertTrue(banner.display)
            
            # Switch back to installed
            registry.update_result("git", installed_result)
            asyncio.run(banner._update_status())
            self.assertFalse(banner.display)

    def test_lldb_is_a_standalone_tool(self) -> None:
        from etui_tools.tab import TOOL_BY_ID

        lldb = TOOL_BY_ID["lldb"]
        self.assertEqual(lldb.display_name, "LLDB Debugger")
        self.assertEqual([probe.name for probe in lldb.probes], ["lldb"])
        self.assertNotIn(
            "lldb",
            [probe.name for probe in TOOL_BY_ID["llvm-embedded"].probes],
        )

if __name__ == "__main__":
    unittest.main()
