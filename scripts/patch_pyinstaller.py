#
#  Kivy 2.3.0 has a issues with PyInstaller 6.5.0 Hooks
#  This script applies a patch has yet to be merged.
#  See https://github.com/kivy/kivy/issues/8653
#

import subprocess
import sys
import os
from pathlib import Path

CURRENT_DIR = Path(__file__).parent.resolve()
FIXED_FILE = CURRENT_DIR.joinpath("pyinstaller_hook_patch.py").resolve()
PATCH_FILE = CURRENT_DIR.joinpath("pyinstaller_hook.patch").resolve()

def run_command(command):
    """Execute a shell command and return its output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error executing command: {command}")
        print(f"stderr: {result.stderr}")
        sys.exit(result.returncode)
    return result.stdout.strip()

def main():
    # Get the path to the Python virtual environment used by Poetry
    pyenv_path = run_command("poetry env info --path")

    # Get the Python version
    pyenv_version = f"{sys.version_info[0]}.{sys.version_info[1]}"

    # Define the paths
    pyhook_path = "site-packages/kivy/tools/packaging/pyinstaller_hooks/__init__.py"
    full_path = os.path.join(pyenv_path, "lib", f"python{pyenv_version}", pyhook_path)

    # Create a patch file
    with open(PATCH_FILE, "w") as patch_file:
        diff_command = f"diff -u {full_path} {FIXED_FILE} || true"  # diff returns non-zero when the files are different
        patch_content = run_command(diff_command)
        patch_file.write(patch_content)

    # Apply the patch
    patch_command = f"patch {full_path} < {PATCH_FILE}"
    run_command(patch_command)

    # Remove the patch file
    os.remove(PATCH_FILE)

if __name__ == "__main__":
    main()