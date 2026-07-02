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
        self._feed_override = feed_override
        self._spindle_override = spindle_override
        self._is_jogging_enabled = is_jogging_enabled
        self._handle_run_pause_resume = handle_run_pause_resume
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
        self._client.on_connect = self._handle_connect
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

    def _handle_connect(self, _client: tcp_client.TCPClient) -> None:
        self._report_connection()
        self._last_machine_snapshot = None
        self._last_macro_snapshot = None
        self._send_machine_state(force=True)
        self._send_macro_list(force=True)
        self._send_position(force=True)

    def _handle_disconnect(self, _client: tcp_client.TCPClient) -> None:
        self._stop_continuous_jog(force=True)
        self._clear_cyd_jogging()
        self._report_disconnection()

    def _send_position(self, force: bool = False) -> None:
        try:
            mx = self._round3(self._cnc.vars.get("mx", 0.0))
            my = self._round3(self._cnc.vars.get("my", 0.0))
            mz = self._round3(self._cnc.vars.get("mz", 0.0))
            wx = self._round3(self._cnc.vars.get("wx", 0.0))
            wy = self._round3(self._cnc.vars.get("wy", 0.0))
            wz = self._round3(self._cnc.vars.get("wz", 0.0))
        except Exception:
            return

        changed = (
            mx != self._last_sent.get("mx") or
            my != self._last_sent.get("my") or
            mz != self._last_sent.get("mz") or
            wx != self._last_sent.get("wx") or
            wy != self._last_sent.get("wy") or
            wz != self._last_sent.get("wz")
        )
        if not force and not changed:
            return

        self._last_sent.update({"mx": mx, "my": my, "mz": mz, "wx": wx, "wy": wy, "wz": wz})
        self._client.send_json({
            "type": "pos",
            "units": "mm",
            "x": mx,
            "y": my,
            "z": mz,
            "mx": mx,
            "my": my,
            "mz": mz,
            "wx": wx,
            "wy": wy,
            "wz": wz,
        })

    def _poll_positions(self, *_args) -> None:
        self._poll_machine_state()
        self._poll_macros()
        self._send_position(force=False)

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
        app = App.get_running_app()
        app_playing = bool(getattr(app, "playing", False)) if app is not None else False
        try:
            machine_playing = int(self._cnc.vars.get("is_playing", 0)) == 1
        except Exception:
            machine_playing = False
        playing = app_playing or machine_playing
        program_running = playing and state == "Run"
        program_paused = playing and state in ("Pause", "Hold")
        jog_allowed = self._cyd_jog_allowed()
        tool = int(self._cnc.vars.get("tool", -1))
        target_tool = int(self._cnc.vars.get("target_tool", -1))
        return {
            "state": state,
            "activity": self._derive_activity(state, atc_state, playing),
            "jog_allowed": jog_allowed,
            "atc_state": atc_state,
            "playing": playing,
            "program_running": program_running,
            "program_paused": program_paused,
            "feed_override": round(float(self._feed_override.get_value())),
            "spindle_override": round(float(self._spindle_override.get_value())),
            "air_on": bool(int(self._cnc.vars.get("sw_air", 0))),
            "playedpercent": round(float(self._cnc.vars.get("playedpercent", 0.0)), 1),
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

    def _send_runtime_result(self, ok: bool, reason: str = "", action: str = "") -> None:
        try:
            self._client.send_json({
                "type": "runtime_result",
                "ok": ok,
                "reason": reason,
                "action": action,
                "ts": int(time.time()),
            })
        except Exception:
            pass

    def _send_position_result(self, ok: bool, reason: str = "", action: str = "", message: str = "") -> None:
        try:
            self._client.send_json({
                "type": "position_result",
                "ok": ok,
                "reason": reason,
                "action": action,
                "message": message,
                "ts": int(time.time()),
            })
        except Exception:
            pass

    def _position_action_allowed(self) -> bool:
        state = str(self._cnc.vars.get("state", "")).lower()
        return state in ("idle", "")

    def _path_origin_available(self) -> bool:
        try:
            xmin = abs(float(self._cnc.vars.get("xmin", 0)))
            ymin = abs(float(self._cnc.vars.get("ymin", 0)))
            worksize_x = float(self._cnc.vars.get("worksize_x", 0))
            worksize_y = float(self._cnc.vars.get("worksize_y", 0))
            return xmin <= worksize_x and ymin <= worksize_y
        except Exception:
            return False

    def _handle_position_request(self, msg: dict) -> None:
        action = str(msg.get("action", "")).lower()
        if not self._position_action_allowed():
            state = str(self._cnc.vars.get("state", "")).lower()
            self._send_position_result(False, f"machine_not_idle:{state}", action)
            return

        try:
            if action == "goto":
                target = str(msg.get("target", "")).lower()
                if target == "work_origin":
                    self._controller.gotoWorkOrigin()
                    self._send_position_result(True, action=action, message="Going to work origin")
                    return
                if target == "path_origin":
                    if not self._path_origin_available():
                        self._send_position_result(False, "path_origin_unavailable", action)
                        return
                    self._controller.gotoPathOrigin()
                    self._send_position_result(True, action=action, message="Going to path origin")
                    return
                self._send_position_result(False, "unsupported_target", action)
                return

            if action == "set_origin":
                axes = str(msg.get("axes", "")).lower()
                if axes == "xy":
                    self._controller.wcsSet(x=0, y=0)
                    self._send_position_result(True, action=action, message="Origin set: X/Y")
                    self._send_machine_state(force=True)
                    return
                if axes == "xyz":
                    self._controller.wcsSet(x=0, y=0, z=0)
                    self._send_position_result(True, action=action, message="Origin set: X/Y/Z")
                    self._send_machine_state(force=True)
                    return
                self._send_position_result(False, "unsupported_axes", action)
                return

            self._send_position_result(False, "unsupported_action", action)
        except Exception as e:
            logger.error(f"CYD: Failed position action {action!r}: {e}")
            self._send_position_result(False, f"error:{e}", action)

    def _handle_runtime_request(self, msg: dict) -> None:
        action = str(msg.get("action", "")).lower()
        try:
            if action == "override":
                target = str(msg.get("target", "")).lower()
                delta = float(msg.get("delta", 0))
                reset = bool(msg.get("reset", False))
                override = self._feed_override if target == "feed" else self._spindle_override if target == "spindle" else None
                if override is None:
                    self._send_runtime_result(False, "bad_override_target", action)
                    return
                if reset:
                    override.set_value(100)
                elif delta > 0:
                    override.on_increase()
                elif delta < 0:
                    override.on_decrease()
                self._send_runtime_result(True, action=action)
                self._send_machine_state(force=True)
                return

            if action == "air":
                if "on" in msg:
                    next_state = bool(msg.get("on"))
                else:
                    next_state = not bool(int(self._cnc.vars.get("sw_air", 0)))
                state = str(self._cnc.vars.get("state", "")).lower()
                if state == "run":
                    self._controller.executeCommand("buffer M7" if next_state else "buffer M9")
                else:
                    self._controller.setAirSwitch(next_state)
                self._send_runtime_result(True, action=action)
                self._send_machine_state(force=True)
                return

            if action == "pause_resume":
                self._handle_run_pause_resume()
                self._send_runtime_result(True, action=action)
                self._send_machine_state(force=True)
                return

            if action == "stop":
                self._controller.abortCommand()
                self._send_runtime_result(True, action=action)
                self._send_machine_state(force=True)
                return

            if action == "probe_cancel":
                self._controller.abortCommand()
                self._send_runtime_result(True, action=action)
                self._send_machine_state(force=True)
                return

            self._send_runtime_result(False, "unsupported_action", action)
        except Exception as e:
            logger.error(f"CYD: Failed runtime action {action!r}: {e}")
            self._send_runtime_result(False, f"error:{e}", action)

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

            if action == "clamp":
                logger.info("CYD: Clamping tool")
                self._controller.clampToolCommand()
                self._send_tool_result(True, action=action)
                return

            if action == "unclamp":
                logger.info("CYD: Unclamping tool")
                self._controller.unclampToolCommand()
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

        # Allowlist: pendant probing commands only.
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

        max_delta = 2.000
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

        # A CYD hybrid jog may have sent step jogs just before promoting to
        # continuous jog. Send a real jog cancel here, even if the controller
        # is still in step mode, so stale step jogs cannot leak across the mode
        # boundary and execute after continuous jogging stops.
        self._stop_continuous_jog(force=True)
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

            if msg_type == "runtime":
                self._handle_runtime_request(msg)
                return

            if msg_type == "position":
                self._handle_position_request(msg)
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
