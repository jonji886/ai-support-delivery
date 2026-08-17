"""React 前端结构测试。

验证 React + TypeScript + Vite 前端项目的关键结构存在。
替代旧的单文件 HTML 测试。
"""

from pathlib import Path
import json

WEB_DIR = Path(__file__).resolve().parents[2] / "apps/web"


def test_package_json_exists_and_has_react_deps() -> None:
    pkg = WEB_DIR / "package.json"
    assert pkg.exists(), "apps/web/package.json must exist"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    assert "react" in data["dependencies"], "must depend on react"
    assert "react-dom" in data["dependencies"], "must depend on react-dom"
    assert "@vitejs/plugin-react" in data["devDependencies"], "must use vite plugin"
    assert "typescript" in data["devDependencies"], "must use typescript"


def test_vite_config_exists() -> None:
    config = WEB_DIR / "vite.config.ts"
    assert config.exists(), "apps/web/vite.config.ts must exist"
    content = config.read_text(encoding="utf-8")
    assert "react()" in content, "vite config must use react plugin"
    assert "proxy" in content, "vite config must have dev proxy for API"


def test_tsconfig_exists_and_strict() -> None:
    config = WEB_DIR / "tsconfig.json"
    assert config.exists(), "apps/web/tsconfig.json must exist"
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["compilerOptions"]["strict"] is True, "typescript must be strict"
    assert data["compilerOptions"]["jsx"] == "react-jsx"


def test_entry_point_exists() -> None:
    main = WEB_DIR / "src/main.tsx"
    assert main.exists(), "apps/web/src/main.tsx must exist"
    content = main.read_text(encoding="utf-8")
    assert "createRoot" in content, "main.tsx must use createRoot"
    assert "App" in content, "main.tsx must render App"


def test_app_component_exists() -> None:
    app = WEB_DIR / "src/App.tsx"
    assert app.exists(), "apps/web/src/App.tsx must exist"
    content = app.read_text(encoding="utf-8")
    assert "GuidePage" in content, "App must render GuidePage"
    assert "ChatPage" in content, "App must render ChatPage"
    assert "TicketsPage" in content, "App must render TicketsPage"
    assert "MemoryInspectorPage" in content, "App must render MemoryInspectorPage"


def test_pages_exist() -> None:
    pages = WEB_DIR / "src/pages"
    assert (pages / "ChatPage.tsx").exists(), "ChatPage must exist"
    assert (pages / "TicketsPage.tsx").exists(), "TicketsPage must exist"
    assert (pages / "ReturnsPage.tsx").exists(), "ReturnsPage must exist"
    assert (pages / "MetricsPage.tsx").exists(), "MetricsPage must exist"
    assert (pages / "TracesPage.tsx").exists(), "TracesPage must exist"
    assert (pages / "ObservabilityPage.tsx").exists(), "ObservabilityPage must exist"
    assert (pages / "MemoryInspectorPage.tsx").exists(), "MemoryInspectorPage must exist"
    assert (pages / "GuidePage.tsx").exists(), "GuidePage must exist"


def test_api_service_exists() -> None:
    api = WEB_DIR / "src/services/api.ts"
    assert api.exists(), "apps/web/src/services/api.ts must exist"
    content = api.read_text(encoding="utf-8")
    assert "assist" in content, "api.ts must export assist function"
    assert "queryOrderLogistics" in content, "api.ts must export queryOrderLogistics"
    assert "submitReturnApplication" in content, "api.ts must export submitReturnApplication"
    assert "listMemory" in content, "api.ts must export listMemory for Memory Inspector"


def test_types_exist() -> None:
    types = WEB_DIR / "src/types/api.ts"
    assert types.exists(), "apps/web/src/types/api.ts must exist"
    content = types.read_text(encoding="utf-8")
    assert "MemoryItem" in content, "types must define MemoryItem"
    assert "MemoryListResponse" in content, "types must define MemoryListResponse"
    assert "Citation" in content, "types must define Citation"
    assert "ToolResponse" in content, "types must define ToolResponse"


def test_chat_page_uses_data_attributes_not_inline_handlers() -> None:
    """验证 React 组件不使用内联 onclick（HTML 属性）。"""
    chat = WEB_DIR / "src/pages/ChatPage.tsx"
    content = chat.read_text(encoding="utf-8")
    # React 使用 onClick prop，不是 HTML onclick 属性
    assert "onClick=" in content, "should use React onClick prop"
    # 不应出现 HTML 字符串拼接的内联 onclick
    assert '"onclick=' not in content, "must not use string-embedded onclick"
    assert "'onclick=" not in content, "must not use string-embedded onclick"


def test_no_inline_script_injection() -> None:
    """验证前端不使用内联 script 注入业务数据。"""
    index = WEB_DIR / "index.html"
    content = index.read_text(encoding="utf-8")
    assert "<script>" not in content, "should not use inline script (use module)"
    assert 'type="module"' in content, "should use ES module"
