# Install missing packages that aren't in the main environment

import subprocess
import sys
import os

def install_package(package_name):
    try:
        # Check if package is already installed
        __import__(package_name.replace("-", "_").replace(".", "_").split("/")[0])
        print(f"✓ {package_name} already installed")
        return True
    except ImportError:
        print(f"Installing {package_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"✓ Successfully installed {package_name}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install {package_name}: {e}")
            return False

# List of packages that might be missing from ai_env
packages_to_install = [
    "onnxruntime",  # For optimized inference
    "psutil",        # System monitoring
    "tqdm",          # Progress bars
    "Werkzeug",      # Web utilities
    # Add any other missing packages here
]

print("Checking for missing packages...")
for package in packages_to_install:
    install_package(package)

print("\\n✅ Package installation check complete!")