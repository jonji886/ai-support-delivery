import os
import tempfile

# Tests must remain deterministic and must never call the user's external model API.
os.environ["DEEPSEEK_ENABLED"] = "false"
os.environ["SUPPORT_DB_PATH"] = tempfile.mktemp(prefix="ai-support-test-", suffix=".db")
os.environ["CONVERSATION_DB_PATH"] = tempfile.mktemp(prefix="ai-support-conversation-test-", suffix=".db")
os.environ["EVENTS_DB_PATH"] = tempfile.mktemp(prefix="ai-support-events-test-", suffix=".db")
os.environ["OBSERVABILITY_DB_PATH"] = tempfile.mktemp(prefix="ai-support-observability-test-", suffix=".db")
os.environ["LOG_LEVEL"] = "CRITICAL"
