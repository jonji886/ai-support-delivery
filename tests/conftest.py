import os

# Tests must remain deterministic and must never call the user's external model API.
os.environ["DEEPSEEK_ENABLED"] = "false"
