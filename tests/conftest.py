import os
import tempfile

# Tests must remain deterministic and must never call the user's external model API.
os.environ["DEEPSEEK_ENABLED"] = "false"
os.environ["SUPPORT_DB_PATH"] = tempfile.mktemp(prefix="ai-support-test-", suffix=".db")
os.environ["CONVERSATION_DB_PATH"] = tempfile.mktemp(prefix="ai-support-conversation-test-", suffix=".db")
