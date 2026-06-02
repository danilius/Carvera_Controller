import json
import socket
import threading
import time
import queue
from typing import Callable, Optional


class TCPClient:
    """
    Minimal persistent TCP client with newline-delimited JSON framing.

    - Maintains a single persistent connection, auto-reconnecting on failure
    - Thread-safe `send_json()` to enqueue outbound messages
    - Parses inbound newline-delimited JSON and dispatches via `on_message`
    - Sends a heartbeat JSON periodically when idle
    """

    def __init__(
        self,
        host_getter: Callable[[], str],
        port_getter: Callable[[], int],
        callback_executor: Callable[[Callable[[], None]], None] = lambda f: f(),
        heartbeat_interval_s: float = 5.0,
    ) -> None:
        self._host_getter = host_getter
        self._port_getter = port_getter
        self._callback_executor = callback_executor
        self._heartbeat_interval_s = heartbeat_interval_s

        self._sock: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._txq: "queue.Queue[str]" = queue.Queue()
        self._last_send_time = 0.0
        self._rx_buf = bytearray()

        self.on_connect: Optional[Callable[["TCPClient"], None]] = None
        self.on_disconnect: Optional[Callable[["TCPClient"], None]] = None
        self.on_message: Optional[Callable[["TCPClient", dict], None]] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            if self._sock:
                self._sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def send_json(self, payload: dict) -> None:
        try:
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            self._txq.put_nowait(line)
        except Exception:
            # If queue is full or serialization fails, drop silently for PoC
            pass

    # Internal
    def _connect(self) -> Optional[socket.socket]:
        host = (self._host_getter() or "").strip()
        try:
            port = int(self._port_getter())
        except Exception:
            port = 0

        if not host or port <= 0:
            time.sleep(1.0)
            return None

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5.0)
            s.connect((host, port))
            s.settimeout(0.2)
            return s
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            return None

    def _handle_connect(self) -> None:
        if self.on_connect:
            callback = self.on_connect
            self._callback_executor(lambda: callback(self))

    def _handle_disconnect(self) -> None:
        if self.on_disconnect:
            callback = self.on_disconnect
            self._callback_executor(lambda: callback(self))

    def _send_heartbeat_if_needed(self) -> None:
        now = time.time()
        if now - self._last_send_time >= self._heartbeat_interval_s:
            self.send_json({"type": "heartbeat", "ts": int(now)})

    def _drain_tx(self) -> None:
        if not self._sock:
            return
        try:
            while True:
                line = self._txq.get_nowait()
                self._sock.sendall(line.encode("utf-8"))
                self._last_send_time = time.time()
        except queue.Empty:
            pass
        except Exception:
            raise

    def _pump_rx(self) -> None:
        if not self._sock:
            return
        try:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("socket closed")
            self._rx_buf.extend(chunk)
            while True:
                nl = self._rx_buf.find(b"\n")
                if nl < 0:
                    break
                line = self._rx_buf[:nl]
                del self._rx_buf[: nl + 1]
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                    if isinstance(msg, dict) and self.on_message and self._callback_executor:
                        callback = self.on_message
                        self._callback_executor(lambda m=msg: callback(self, m))
                except Exception:
                    # Ignore malformed JSON
                    pass
        except socket.timeout:
            pass
        except Exception:
            raise

    def _run(self) -> None:
        while self._running:
            try:
                self._sock = self._connect()
                if not self._sock:
                    continue
                self._handle_connect()
                self._last_send_time = 0.0
                # Initial heartbeat to confirm link
                self._send_heartbeat_if_needed()
                self._drain_tx()

                while self._running and self._sock:
                    # Send heartbeat when idle
                    self._send_heartbeat_if_needed()
                    # TX first to reduce latency
                    self._drain_tx()
                    # RX
                    self._pump_rx()
            except Exception:
                pass
            finally:
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None
                self._handle_disconnect()
                # Backoff before reconnect
                for _ in range(10):
                    if not self._running:
                        break
                    time.sleep(0.1)
