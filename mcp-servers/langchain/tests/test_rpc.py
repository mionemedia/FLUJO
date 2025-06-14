"""Test script for MCP server RPC methods."""
import json
import sys
import subprocess
import time
import os
from typing import Dict, Any

def send_request(request: Dict[str, Any]) -> None:
    """Send a JSON-RPC request to the server's stdin."""
    json_str = json.dumps(request) + "\n"
    sys.stdout.buffer.write(json_str.encode())
    sys.stdout.buffer.flush()

def main():
    # Test requests
    requests = [
        {
            "jsonrpc": "2.0",
            "method": "list_tools",
            "id": 1,
            "params": {}
        },
        {
            "jsonrpc": "2.0",
            "method": "invoke_tool",
            "id": 2,
            "params": {
                "name": "echo",
                "arguments": {"message": "Hello, MCP!"}
            }
        },
        {
            "jsonrpc": "2.0",
            "method": "invoke_tool",
            "id": 3,
            "params": {
                "name": "add",
                "arguments": {"a": 40, "b": 2}
            }
        },
        {
            "jsonrpc": "2.0",
            "method": "ping",
            "id": 4,
            "params": {}
        },
        {
            "jsonrpc": "2.0",
            "method": "shutdown",
            "id": 5,
            "params": {}
        }
    ]

    # Get absolute paths for reliable script execution
    base_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = os.path.join(base_dir, "venv", "Scripts", "python.exe")
    server_script = os.path.join(base_dir, "mcp_server.py")

    # Start server process
    server_proc = subprocess.Popen(
        [python_exe, "-u", server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        cwd=base_dir
    )

    try:
        # Wait for handshake
        handshake = server_proc.stdout.readline()
        print("Handshake received:", handshake.decode().strip())

        # Send test requests
        for request in requests:
            print(f"\nSending {request['method']} request...")
            server_proc.stdin.write(json.dumps(request).encode() + b"\n")
            server_proc.stdin.flush()
            
            # Read response
            response = server_proc.stdout.readline()
            print(f"Response: {response.decode().strip()}")
            
            # Small delay between requests
            time.sleep(0.1)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Wait for server to exit
        server_proc.wait(timeout=5)
        
        # Print any stderr output
        stderr = server_proc.stderr.read().decode()
        if stderr:
            print("\nServer logs:", stderr)

if __name__ == "__main__":
    main()
