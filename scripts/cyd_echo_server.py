import argparse
import json
import socket


def run_server(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        s.listen(1)
        print(f"[CYD Echo] Listening on {host}:{port} ...")
        conn, addr = s.accept()
        print(f"[CYD Echo] Connection from {addr}")
        with conn:
            buf = b""
            while True:
                data = conn.recv(4096)
                if not data:
                    print("[CYD Echo] Client disconnected")
                    break
                buf += data
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    line = buf[:nl]
                    buf = buf[nl+1:]
                    try:
                        msg = json.loads(line.decode("utf-8"))
                    except Exception:
                        print(f"[CYD Echo] (malformed) {line!r}")
                        continue
                    
                    print(f"[CYD Echo] {msg}")
                    
                    # Simulate ESP32 staged manual tool-change workflow.
                    if msg.get("type") == "tool_action_required":
                        action = msg.get("action")
                        tool = msg.get("tool")
                        message = msg.get("message", "")
                        
                        print(f"\n{'='*60}")
                        print(f"TOOL ACTION REQUIRED:")
                        print(f"  Action: {action}")
                        print(f"  Tool: {tool}")
                        print(f"  Message: {message}")
                        print(f"{'='*60}")
                        print("Step 1/3: Press Enter to send NEXT (resume for action)")
                        print(f"{'='*60}\n")

                        input()

                        # Next button after "tool change required"
                        next1 = {
                            "type": "tool_change_next",
                            "action": action
                        }
                        conn.sendall((json.dumps(next1) + '\n').encode("utf-8"))
                        print(f"[CYD Echo] Sent: {next1}")

                        print("Step 2/3: Press Enter to send TOOL_INSERTED")
                        input()
                        inserted = {
                            "type": "tool_inserted",
                            "action": action,
                            "tool": tool
                        }
                        conn.sendall((json.dumps(inserted) + '\n').encode("utf-8"))
                        print(f"[CYD Echo] Sent: {inserted}")

                        print("Step 3/3: Press Enter to send NEXT (final resume)")
                        input()
                        next2 = {
                            "type": "tool_change_next",
                            "action": action
                        }
                        conn.sendall((json.dumps(next2) + '\n').encode("utf-8"))
                        print(f"[CYD Echo] Sent: {next2}")
                        print("Staged tool change flow complete.\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CYD Echo Server with tool change simulation")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=9876)
    args = ap.parse_args()
    run_server(args.host, args.port)
