.PHONY: dev web web-dev test eval verify lint demo-oms-timeout clean help

# Default: show available commands
help:
	@echo "AI Support Delivery - 开发命令"
	@echo ""
	@echo "Backend:"
	@echo "  make dev        启动 API 开发服务器 (port 8000)"
	@echo ""
	@echo "Frontend:"
	@echo "  make web-dev    启动 React 开发服务器 (port 5173, Vite + API proxy)"
	@echo "  make web-build   构建 React 生产产物 (dist/)"
	@echo ""
	@echo "Testing:"
	@echo "  make test       运行全部单元测试和集成测试"
	@echo "  make eval       运行全部评测 (核心 + 意图 + 记忆 + Skill + RAG)"
	@echo "  make verify     运行测试 + 评测 + 构建验证 (发布前完整检查)"
	@echo "  make demo-oms-timeout 复现 OMS 超时 → 重试 → 安全转人工"
	@echo ""
	@echo "Other:"
	@echo "  make lint       静态检查"
	@echo "  make clean      清理 runtime 和缓存"

# === Backend ===
dev:
	python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload

# === Frontend ===
web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build

web-install:
	cd apps/web && npm install

# === Testing ===
test:
	python3 -m pytest -q

eval:
	python3 evals/validate_dataset.py
	python3 evals/run_eval.py
	python3 evals/run_intent_eval.py
	python3 evals/run_memory_eval.py
	python3 evals/run_memory_eval_extended.py
	python3 evals/run_skill_eval.py
	python3 evals/run_policy_eval.py
	python3 evals/model_eval.py
	python3 evals/render_acceptance_report.py

model-eval:
	python3 evals/model_eval.py

verify: test eval
	@echo "--- Build Verification ---"
	python3 -c "from apps.api.main import app; print('Backend Build OK')"
	@echo "--- Verify Complete ---"

# === Reproducible incident demo ===
demo-oms-timeout:
	python3 scripts/demo_oms_timeout.py

# === Linting ===
lint:
	python3 -m ruff check .

# === Cleanup ===
clean:
	rm -rf runtime/*.db runtime/chroma __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
