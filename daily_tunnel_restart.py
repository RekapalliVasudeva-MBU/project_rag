import subprocess
import time
import re
import sys
import os
import signal
from pyngrok import ngrok

def run_cmd(cmd, timeout=10):
    """Run command and return (success, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Timeout"
    except Exception as e:
        return False, "", str(e)

def main():
    project_dir = r"C:\Users\valte\project_rag"

    print(f"=== Daily Tunnel Restart - {time.ctime()} ===")

    # Kill any existing ngrok processes
    print("1. Stopping old tunnel...")
    run_cmd("taskkill /F /IM ngrok.exe 2>nul")
    time.sleep(2)

    # Start ngrok tunnel
    print("2. Starting ngrok tunnel...")
    auth_token = os.environ.get("NGROK_AUTH_TOKEN", "")
    if not auth_token:
        print("   ERROR: NGROK_AUTH_TOKEN not set")
        return 1

    ngrok.set_auth_token(auth_token)
    try:
        tunnel = ngrok.connect(addr=8000, proto="https")
        public_url = tunnel.public_url
    except Exception as e:
        print(f"   ERROR: Failed to start ngrok: {e}")
        return 1

    print(f"   ngrok URL: {public_url}")

    # 3. Verify tunnel works
    print("\n3. Verifying tunnel...")
    time.sleep(3)
    success, stdout, stderr = run_cmd(f'curl -s {public_url}/api/health', timeout=15)
    if success and '"status":"ok"' in stdout:
        print("   Health check passed")
    else:
        print(f"   Warning: health check result: {stdout[:200]}")

    # 4. Report the URL
    print(f"\n{'=' * 60}")
    print(f"Daily ngrok Tunnel URL - {time.strftime('%Y-%m-%d')}")
    print(f"Website:     {public_url}")
    print(f"Health:      {public_url}/api/health")
    print(f"Chat API:    {public_url}/api/chat")
    print(f"Download:    {public_url}/download/aether")
    print(f"RAG Docs:    {public_url}/knowledge")
    print(f"\nThis URL is valid until ngrok token expires or tunnel is stopped.")
    print(f"Server runs on your laptop - laptop on = site on.")

    # Process continues running in background (ngrok keeps it alive)
    return 0

if __name__ == "__main__":
    sys.exit(main())