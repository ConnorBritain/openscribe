#!/usr/bin/env python3
"""
CitrixTranscriber CLI
A slim command-line client that interfaces with the Local API to drive the application.
"""

import argparse
import json
import socket
import sys
import urllib.request
import urllib.error

# We check what port the configuration exposes without dragging in heavy dependencies if possible
# But importing config.py is usually okay if pyaudio is installed. Let's do a safe import.
LOCAL_API_PORT = 5050
try:
    # Attempt to load port from configuration
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from src.config.config import LOCAL_API_PORT as CONF_PORT
    LOCAL_API_PORT = CONF_PORT
except ImportError:
    pass

def send_request(endpoint, method="POST"):
    """Send an HTTP request to the local API."""
    url = f"http://127.0.0.1:{LOCAL_API_PORT}/{endpoint}"
    req = urllib.request.Request(url, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.getcode()
            body = response.read().decode('utf-8')
            try:
                data = json.loads(body)
                return True, data
            except json.JSONDecodeError:
                return True, {"message": body}
                
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            data = json.loads(body)
            # Use the server's error message if provided
            return False, data
        except json.JSONDecodeError:
            return False, {"message": f"HTTP Error {e.code}: {e.reason}"}
            
    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError):
            return False, {"message": f"Connection refused. Is the CitrixTranscriber backend running?"}
        return False, {"message": f"URL Error: {e.reason}"}
        
    except socket.timeout:
        return False, {"message": "Request timed out"}
    
    except Exception as e:
        return False, {"message": f"Unexpected error: {str(e)}"}

def main():
    parser = argparse.ArgumentParser(description="CitrixTranscriber CLI Controller")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    parser_start = subparsers.add_parser("start", help="Start dictation")
    parser_stop = subparsers.add_parser("stop", help="Stop dictation and process audio")
    parser_status = subparsers.add_parser("status", help="Get application status")

    args = parser.parse_args()

    if args.command == "start":
        print("Starting dictation...")
        success, response = send_request("start", method="POST")
        if success:
            print(f"Success: {response.get('message', 'Started dictation')}")
        else:
            print(f"Error: {response.get('message', 'Failed to start dictation')}")
            sys.exit(1)
            
    elif args.command == "stop":
        print("Stopping dictation...")
        success, response = send_request("stop", method="POST")
        if success:
            print(f"Success: {response.get('message', 'Stopped dictation')}")
        else:
            print(f"Error: {response.get('message', 'Failed to stop dictation')}")
            sys.exit(1)
            
    elif args.command == "status":
        success, response = send_request("status", method="GET")
        if success:
            print("Status:")
            for key, value in response.items():
                print(f"  {key}: {value}")
        else:
            print(f"Error: {response.get('message', 'Failed to get status')}")
            sys.exit(1)
            
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
