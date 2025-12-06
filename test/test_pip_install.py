#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from services.installer.installer import reinstall_pip_and_install, get_venv_python

# Test with the project root (not the venv path directly)
print(f"Testing pip installation for project: {project_root}")

try:
    # Create a mock venv path to test
    test_venv_python = Path(r"D:\Projects\AutoScriptor\.venv_test\Scripts\python.exe")
    print(f"Testing with venv python: {test_venv_python}")

    # Check if pip is available
    import subprocess
    try:
        subprocess.check_call([str(test_venv_python), "-c", "import pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Pip is already available")
    except subprocess.CalledProcessError:
        print("Pip not available, testing installation...")
        # Test the pip installation logic manually
        get_pip_script = project_root / "services" / "installer" / "get-pip.py"
        if get_pip_script.exists():
            print("Installing pip using portable get-pip.py...")
            subprocess.check_call([str(test_venv_python), str(get_pip_script)])
            print("Pip installation completed successfully!")
        else:
            print("get-pip.py not found")

except Exception as e:
    print(f"Error: {e}")
