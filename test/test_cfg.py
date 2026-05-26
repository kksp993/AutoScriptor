import os
import sys

# Ensure the project root is in sys.path before attempting imports
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from AutoScriptor.utils.app_config import cfg

if __name__ == "__main__":
    cfg.load_config(pwd=os.getenv("PASSWORD"))
    print(cfg)