import json
import re
import time
from typing import Callable

import logging
logger = logging.getLogger(__name__)

from kivy.clock import Clock
from kivy.config import Config as KivyConfig
from kivy.app import App

from . import tcp_client


class CYD:
    def __init__(self, controller, cnc,
                 feed_override,
                 spindle_override,
                 is_jogging_enabled: Callable[[], None],
                 handle_run_pause_resume: Callable[[], None],
                 handle_probe_z: Callable[[], None],
                 open_probing_popup: Callable[[], None],
                 report_connection: Callable[[], None],
                 report_disconnection: Callable[[], None],
                 update_ui_on_button_press: Callable[[str], None] = None,
                 update_ui_on_jog_stop: Callable[[], None] = None) -> None:
        self._controller = controller
        self._cnc = cnc
        self._is_jogging_enabled = is_jogging_enabled
        self._report_connection = report_connection
        self._report_disconnection = report_disconnection
        self._jog_session_until = 0.0
        self._last_full_stop_seq = 0
        self._clear_jog_ev = None

        def get_host():
            try:
                return KivyConfig.get("carvera", "cyd_pendant_host")
            except Exception:
                return ""

        def get_port():
            try:
                return int(KivyConfig.get("carvera", "cyd_pendant_port"))
            except Exception:
                return 9876

        self._client = tcp_client.TCPClient(get_host, get_port, callback_executor=self.executor)
        self._client.on_connect = lambda _: self._report_connection()
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_incoming
        self._client.start()

        self._last_sent = {"x": 0.0, "y": 0.0, "z": 0.0}
        self._last_machine_snapshot = None
        self._last_macro_snapshot = None

        # Poll at 5 Hz; send position changes + machine state changes.
        self._poll_ev = Clock.schedule_interval(self._poll_positions, 0.2)

    def close(self) -> None:
        try:
            if self._poll_ev is not None:
                self._poll_ev.cancel()
        except Exception:
            pass
        try:
            self._client.stop()
        except Exception:
            pass

    def executor(self, f: Callable[[], None]) -> None:
        Clock.schedule_once(lambda _: f(), 0)

    def _round3(self, v: float) -> float:
        try:
            return round(float(v), 3)
        except Exception:
            return 0.0

    def _stop_continuous_jog(self, force: bool = False) -> None:
        try:
            if force and self._controller.stream is not None:
                self._controller.stream.send(b"\031")
            else:
                self._controller.stopContinuousJog()
            self._controller.continuous_jog_active = False
        except Exception:
            pass

    def _set_cyd_jogging(self, active: bool) -> None:
        app = App.get_running_app()
        if app is not None:
            app.cyd_jogging = bool(active)

    def _mark_cyd_jogging(self, hold_s: float = 1.0) -> None:
        self._set_cyd_jogging(True)
        try:
            if self._clear_jog_ev is not None:
                self._clear_jog_ev.cancel()
        except Exception:
            pass
        self._clear_jog_ev = Clock.schedule_once(lambda *_: self._set_cyd_jogging(False), hold_s)

    def _clear_cyd_jogging(self) -> None:
        try:
            if self._clear_jog_ev is not None:
                self._clear_jog_ev.cancel()
        except Exception:
            pass
        self._clear_jog_ev = None
        self._set_cyd_jogging(False)

    def _handle_disconnect(self, _client: tcp_client.TCPClient) -> None:
        self._stop_continuous_jog(force=True)
        self._clear_cyd_jogging()
        self._report_disconnection()

    def _poll_positions(self, *_args) -> None:
        self._poll_machine_state()
        self._poll_macros()

        try:
            mx = self._round3(self._cnc.vars.get("mx", 0.0))
            my = self._round3(self._cnc.vars.get("my", 0.0))
            mz = self._round3(self._cnc.vars.get("mz", 0.0))
        except Exception:
            return

        changed = (
            mx != self._last_sent.get("x") or
            my != self._last_sent.get("y") or
            mz != self._last_sent.get("z")
        )
        if not changed:
            return

        self._last_sent.update({"x": mx, "y": my, "z": mz})
        self._client.send_json({
            "type": "pos",
            "coord": "machine",
            "units": "mm",
            "x": mx,
            "y": my,
            "z": mz,
        })

    def _derive_activity(self, state: str, atc_state: int, playing: bool) -> str:
        s = str(state).lower()
        if s == "idle":
            return "idle"
        if s == "sleep":
            return "sleeping"
        if s == "alarm":
            return "alarm"
        if s == "pause":
            return "paused"
        if s == "hold":
            return "holding"
        if s == "wait":
            return "waiting"
        if s == "tool":
            return "changing_tool"
        if atc_state == 5:
            return "probing"
        if atc_state in (1, 2, 3):
            return "changing_tool"
        if atc_state == 6:
            return "leveling"
        if playing and s == "run":
            return "running_gcode"
        if s == "run":
            return "running"
        return s or "unknown"

    def _tool_label(self, tool: int) -> str:
        if tool == 0:
            return "Probe"
        if tool == 8888:
            return "Laser"
        if 999990 <= tool <= 999999:
            return "3D Probe"
        if tool > 0:
            return f"T{tool}"
        return "No Tool"

    def _jog_session_active(self) -> bool:
        return time.monotonic() < self._jog_session_until

    def _cyd_jog_allowed(self) -> bool:
        try:
            return bool(self._is_jogging_enabled()) or self._jog_session_active()
        except Exception:
            return self._jog_session_active()

    def _machine_snapshot(self) -> dict:
        state = str(self._cnc.vars.get("state", "N/A"))
        atc_state = int(self._cnc.vars.get("atc_state", 0))
        playedlines = int(self._cnc.vars.get("playedlines", -1))
        playing = playedlines > 0
        jog_allowed = self._cyd_jog_allowed()
        tool = int(self._cnc.vars.get("tool", -1))
        target_tool = int(self._cnc.vars.get("target_tool", -1))
        return {
            "state": state,
            "activity": self._derive_activity(state, atc_state, playing),
            "jog_allowed": jog_allowed,
            "atc_state": atc_state,
            "playing": playing,
            "tool": tool,
            "tool_label": self._tool_label(tool),
            "target_tool": target_tool,
            "target_tool_label": self._tool_label(target_tool),
        }

    def _send_machine_state(self, force: bool = False, response_to: str = "") -> None:
        snapshot = self._machine_snapshot()
        if not force and snapshot == self._last_machine_snapshot:
            return
        payload = {"type": "machine_state", **snapshot, "ts": int(time.time())}
        if response_to:
            payload["response_to"] = response_to
        self._client.send_json(payload)
        self._last_machine_snapshot = snapshot

    def _poll_machine_state(self) -> None:
        try:
            self._send_machine_state(force=False)
        except Exception:
            pass

    def _macro_list(self) -> list:
        macros = []
        for idx in range(1, 11):
            macro_key = f"pendant_macro_{idx}"
            try:
                macro_value = KivyConfig.get("carvera", macro_key)
            except Exception:
                macro_value = ""

            if not macro_value:
                continue

            try:
                macro_data = json.loads(macro_value)
            except Exception:
                continue

            name = str(macro_data.get("name", "")).strip()
            gcode = str(macro_data.get("gcode", "")).strip()
            if not name or not gcode:
                continue

            if name.lower() == f"macro {idx}".lower():
                continue

            macros.append({"id": idx, "name": name[:24]})
        return macros

    def _send_macro_list(self, force: bool = False) -> None:
        macros = self._macro_list()
        if not force and macros == self._last_macro_snapshot:
            return
        self._client.send_json({"type": "macro_list", "macros": macros, "ts": int(time.time())})
        self._last_macro_snapshot = macros

    def _poll_macros(self) -> None:
        try:
            self._send_macro_list(force=False)
        except Exception:
            pass

    def _send_macro_result(self, ok: bool, reason: str = "", macro_id: int = -1) -> None:
        try:
            self._client.send_json({
                "type": "macro_result",
                "ok": ok,
                "reason": reason,
                "id": macro_id,
                "ts": int(time.time()),
            })
        except Exception:
            pass

    def _handle_macro_request(self, msg: dict) -> None:
        action = str(msg.get("action", "")).lower()
        if action != "run":
            self._send_macro_result(False, "unsupported_action")
            return

        try:
            macro_id = int(msg.get("id", 0))
        except Exception:
            self._send_macro_result(False, "invalid_id")
            return

        macros = {macro["id"]: macro for macro in self._macro_list()}
        if macro_id not in macros:
            self._send_macro_result(False, "not_named", macro_id)
            return

        macro_key = f"pendant_macro_{macro_id}"
        try:
            macro_data = json.loads(KivyConfig.get("carvera", macro_key))
            lines = macro_data.get("gcode", "").splitlines()
            for line in lines:
                line = line.strip()
                if line:
                    self._controller.executeCommand(line)
            logger.info(f"CYD: Ran macro {macro_id}: {macros[macro_id]['name']}")
            self._send_macro_result(True, macro_id=macro_id)
        except Exception as e:
            logger.error(f"CYD: Failed to run macro {macro_id}: {e}")
            self._send_macro_result(False, f"error:{e}", macro_id)

    def forward_mdi_line(self, line: str, level: int) -> None:
        pass

    def notify_tool_action(self, action: str, tool: int, message: str) -> None:
        pass

    def _send_jog_result(self, ok: bool, reason: str = "", command: str = "") -> None:
        try:
            self._client.send_json({
                "type": "jog_result",
                "ok": ok,
                "reason": reason,
                "command": command,
            })
        except Exception:
            pass

    def _send_gcode_result(self, ok: bool, reason: str = "", command: str = "") -> None:
        try:
            self._client.send_json({
                "type": "gcode_result",
                "ok": ok,
                "reason": reason,
                "command": command,
            })
        except Exception:
            pass

    def _send_tool_result(self, ok: bool, reason: str = "", action: str = "", tool: int = -1) -> None:
        try:
            self._client.send_json({
                "type": "tool_result",
                "ok": ok,
                "reason": reason,
                "action": action,
                "tool": tool,
            })
        except Exception:
            pass

    def _tool_change_allowed(self) -> bool:
        state = str(self._cnc.vars.get("state", "")).lower()
        atc_state = int(self._cnc.vars.get("atc_state", 0))
        playedlines = int(self._cnc.vars.get("playedlines", -1))
        return self._derive_activity(state, atc_state, playedlines > 0) == "idle"

    def _handle_tool_request(self, msg: dict) -> None:
        action = str(msg.get("action", "")).lower()

        if not self._tool_change_allowed():
            state = str(self._cnc.vars.get("state", "")).lower()
            atc_state = int(self._cnc.vars.get("atc_state", 0))
            playedlines = int(self._cnc.vars.get("playedlines", -1))
            activity = self._derive_activity(state, atc_state, playedlines > 0)
            logger.warning(f"CYD: Rejected tool action {action!r}; activity={activity}, state={state}, atc_state={atc_state}, playedlines={playedlines}")
            self._send_tool_result(False, f"not_idle:{activity}", action)
            return

        try:
            if action == "drop":
                logger.info("CYD: Dropping current tool")
                self._controller.dropToolCommand()
                self._send_tool_result(True, action=action)
                return

            if action == "change":
                tool = int(msg.get("tool", -999999))
                if tool not in (0, 999990, 1, 2, 3, 4, 5, 6):
                    self._send_tool_result(False, "unsupported_tool", action, tool)
                    return
                logger.info(f"CYD: Changing tool to {tool}")
                self._controller.changeToolCommand(tool)
                self._send_tool_result(True, action=action, tool=tool)
                return

            self._send_tool_result(False, "unsupported_action", action)
        except Exception as e:
            logger.error(f"CYD: Failed to execute tool action: {e}")
            self._send_tool_result(False, f"error:{e}", action)

    def _handle_gcode_request(self, msg: dict) -> None:
        line = str(msg.get("line", "")).strip()
        if not line:
            self._send_gcode_result(False, "empty_line")
            return

        # Allowlist: only M466 (single-axis probe) for now.
        if not re.match(r'^M46[126]\b', line, re.IGNORECASE):
            logger.warning(f"CYD: Rejected gcode not on allowlist: {line!r}")
            self._send_gcode_result(False, "not_allowed")
            return

        state = str(self._cnc.vars.get("state", "")).lower()
        if state not in ("idle", ""):
            logger.warning(f"CYD: Rejected gcode because machine not idle: {state}")
            self._send_gcode_result(False, f"machine_not_idle:{state}")
            return

        logger.info(f"CYD: Executing gcode: {line!r}")
        try:
            self._controller.executeCommand(line)
            self._send_gcode_result(True, command=line)
        except Exception as e:
            logger.error(f"CYD: Failed to execute gcode: {e}")
            self._send_gcode_result(False, f"error:{e}")

    def _handle_jog_request(self, msg: dict) -> None:
        self._mark_cyd_jogging(hold_s=1.2)
        try:
            step_jog_allowed = bool(self._is_jogging_enabled())
        except Exception:
            step_jog_allowed = False

        if not step_jog_allowed:
            logger.warning("CYD: Ignored jog request because jogging is disabled")
            self._send_jog_result(False, "jogging_disabled")
            return

        axis = str(msg.get("axis", "")).upper()
        if axis not in ("X", "Y", "Z"):
            logger.warning(f"CYD: Ignored jog request for unsupported axis: {axis}")
            self._send_jog_result(False, "unsupported_axis")
            return

        try:
            delta = float(msg.get("delta", 0.0))
        except Exception:
            logger.warning("CYD: Ignored jog request with invalid delta")
            self._send_jog_result(False, "invalid_delta")
            return

        max_delta = 1.000
        tolerance = 0.0005
        if abs(delta) <= 0.0 or abs(delta) > (max_delta + tolerance):
            logger.warning(f"CYD: Ignored jog request outside first-test limit: {delta}")
            self._send_jog_result(False, f"outside_first_test_limit:{delta:.6f}")
            return

        direction = "-" if delta < 0 else ""
        command = f"{axis}{direction}{abs(delta):.3f}"
        self._controller.jog_mode = self._controller.JOG_MODE_STEP
        self._controller.jog(command)

    def _handle_continuous_jog_request(self, msg: dict) -> None:
        action = str(msg.get("action", "")).lower()
        try:
            seq = int(msg.get("seq", 0))
        except Exception:
            seq = 0

        if action in ("stop", "full_stop"):
            self._stop_continuous_jog(force=action == "full_stop")
            if action == "full_stop":
                self._jog_session_until = 0.0
                self._last_full_stop_seq = max(self._last_full_stop_seq, seq)
                self._clear_cyd_jogging()
            else:
                self._mark_cyd_jogging(hold_s=0.3)
            return

        if action != "start":
            self._send_jog_result(False, "unsupported_continuous_action")
            return

        if not self._cyd_jog_allowed():
            logger.warning("CYD: Ignored continuous jog because jogging is disabled")
            self._send_jog_result(False, "jogging_disabled")
            return

        axis = str(msg.get("axis", "")).upper()
        if axis not in ("X", "Y", "Z"):
            self._send_jog_result(False, "unsupported_axis")
            return

        try:
            direction_value = int(msg.get("dir", 0))
            feed = float(msg.get("feed", 0))
        except Exception:
            self._send_jog_result(False, "invalid_continuous_jog")
            return

        if direction_value == 0:
            self._send_jog_result(False, "invalid_direction")
            return

        if seq and seq <= self._last_full_stop_seq:
            return

        feed = max(1.0, min(feed, 3000.0))
        if axis == "Z":
            feed = min(feed, 800.0)

        direction = "-" if direction_value < 0 else ""
        command = f"{axis}{direction}1"

        self._stop_continuous_jog()
        self._mark_cyd_jogging(hold_s=1.0)
        self._controller.setJogMode(self._controller.JOG_MODE_CONTINUOUS)
        self._controller.startContinuousJog(command, feed)
        self._jog_session_until = time.monotonic() + 1.0

    def _handle_incoming(self, _client: tcp_client.TCPClient, msg: dict) -> None:
        try:
            msg_type = str(msg.get("type", ""))

            if msg_type in ("machine_state_query", "get_machine_state", "state_query"):
                self._send_machine_state(force=True, response_to=msg_type)
                return

            if msg_type in ("macro_query", "get_macros"):
                self._send_macro_list(force=True)
                return

            if msg_type == "jog":
                self._handle_jog_request(msg)
                return

            if msg_type == "jog_cont":
                self._handle_continuous_jog_request(msg)
                return

            if msg_type == "tool":
                self._handle_tool_request(msg)
                return

            if msg_type == "gcode":
                self._handle_gcode_request(msg)
                return

            if msg_type == "macro":
                self._handle_macro_request(msg)
                return

            if msg_type == "ping":
                try:
                    self._client.send_json({"type": "pong", "ts": msg.get("ts")})
                except Exception:
                    pass
                return

            logger.debug(f"CYD incoming: {msg}")
        except Exception as e:
            logger.error(f"CYD: Error handling incoming message: {e}")
