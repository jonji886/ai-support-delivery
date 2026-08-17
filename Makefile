.PHONY: dev test eval verify lint clean help

# Default: show available commands
help:
	@echo "AI Support Delivery - 开发命令"
	@echo ""
	@echo "  make dev      启动 API 开发服务器 (port 8000)"
	@echo "  make web      启动前端静态服务器 (port 8080)"
	@echo "  make test     运行全部单元测试和集成测试"
	@echo "  make eval     运行全部评测 (核心 + 意图 + 记忆 + Skill + RAG)"
	@echo "  make verify   运行测试 + 评测 + 构建验证 (发布前完整检查)"
	@echo "  make lint     静态检查"
	@echo "  make clean    清理 runtime 和缓存"

dev:
	python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload

web:
	python3 -m http.server 8080 --bind 127.0.0.1 --directory apps/web

test:
	python3 -m pytest -q

eval:
	python3 evals/validate_dataset.py
	python3 evals/run_eval.py
	python3 evals/run_intent_eval.py
	python3 evals/run_memory_eval.py
	python3 evals/run_skill_eval.py
	python3 evals/run_policy_eval.py

verify: test eval
	@echo "--- Build Verification ---"
	python3 -c "from apps.api.main import app; print('Build OK')"
	@echo "--- Verify Complete ---"

lint:
	@command -v pyflakes >/dev/null 2>&1 && python3 -m pyflakes apps/ evals/ tests/ || echo "pyflakes not installed, skipping"

clean:
	rm -rf runtime/*.db __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
