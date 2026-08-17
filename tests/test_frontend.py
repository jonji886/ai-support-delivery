"""旧单文件 HTML 前端测试已废弃。

前端已从单文件 index.html 迁移到 React + TypeScript + Vite。
新测试位于 tests/frontend/test_react_structure.py。
"""
import pytest

pytest.skip("Frontend migrated to React; see tests/frontend/", allow_module_level=True)
