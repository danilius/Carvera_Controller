import math

from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.modalview import ModalView

from ... import Controller
from ...CNC import CNC
from ...Controller import NOT_CONNECTED
from .operations.OperationsBase import OperationsBase
from .operations.OutsideCorner.OutsideCornerOperationType import OutsideCornerOperationType
from .operations.OutsideCorner.OutsideCornerSettings import OutsideCornerSettings
from .operations.InsideCorner.InsideCornerSettings import InsideCornerSettings
from .operations.SingleAxis.SingleAxisProbeOperationType import \
    SingleAxisProbeOperationType
from .operations.SingleAxis.SingleAxisProbeSettings import SingleAxisProbeSettings
from .preview.ProbingPreviewPopup import ProbingPreviewPopup

from .operations.InsideCorner.InsideCornerOperationType import InsideCornerOperationType

from .operations.Bore.BoreOperationType import BoreOperationType
from .operations.Bore.BoreParameterDefinitions import BoreParameterDefinitions
from .operations.Bore.BoreSettings import BoreSettings

from .operations.Boss.BossOperationType import BossOperationType
from .operations.Boss.BossSettings import BossSettings

from .operations.Angle.AngleOperationType import AngleOperationType
from .operations.Angle.AngleSettings import AngleSettings

from .operations.Calibration.CalibrationOperationType import CalibrationOperationType
from .operations.Calibration.CalibrationSettings import CalibrationSettings

from .operations.ProbeTip.ProbeTipOperationType import ProbeTipOperationType
from .operations.ProbeTip.ProbeTipSettings import ProbeTipSettings

from .operations.FourthAxis.FourthAxisOperationType import FourthAxisOperationType
from .operations.FourthAxis.FourthAxisSettings import FourthAxisSettings

import logging
logger = logging.getLogger(__name__)

from kivy.app import App

import webbrowser
from .operations.ConfigUtils import ConfigUtils


class RingGaugeDriftPopup(ModalView):
    apply_probe_correction = BooleanProperty(True)
    persist_correction = BooleanProperty(False)
    command_text = StringProperty("")
    is_running = BooleanProperty(False)
    points_text = StringProperty("")
    primary_button_text = StringProperty("Start Probe")
    result_text = StringProperty("")
    step_count = NumericProperty(3)
    step_index = NumericProperty(0)
    step_text = StringProperty("")
    stored_correction_text = StringProperty("")

    config_filename = "ring-gauge-drift-settings.json"

    steps = (
        ("Marked cable position", "Rotate the probe to the USB cable position you will use for normal probing. Place a mark on the spindle or collar aligned with the cable, then probe the ring."),
        ("Rotate 120 degrees left", "Return to the marked cable position, rotate the probe roughly 120 degrees to the left, then probe the ring again."),
        ("Rotate 120 degrees right", "Return to the marked cable position, rotate the probe roughly 120 degrees to the right, then probe the ring one more time."),
    )

    def __init__(self, controller, get_probe_tip_config, **kwargs):
        self.controller = controller
        self.get_probe_tip_config = get_probe_tip_config
        self.on_correction_changed = kwargs.pop("on_correction_changed", None)
        self.config = ConfigUtils.load_config(self.config_filename)
        self.persist_correction = self.config.get("enabled", "1") == "1"
        self.points = []
        self.current_correction = None
        self._waiting_for_probe = False
        self._probe_started_busy = False
        self._probe_poll_count = 0
        super(RingGaugeDriftPopup, self).__init__(**kwargs)
        self.reset()

    def reset(self):
        self.points = []
        self.current_correction = None
        self.step_index = 0
        self.apply_probe_correction = True
        self.persist_correction = self.config.get("enabled", "1") == "1"
        self.is_running = False
        self._waiting_for_probe = False
        self._probe_started_busy = False
        self._probe_poll_count = 0
        self.command_text = ""
        self.result_text = "Clamp the ring gauge so it cannot move. Mark the USB cable position you will use for normal probing, then align the cable to that mark before future probing."
        self.update_stored_correction_text()
        self.update_display()

    def on_open(self):
        self.reset()

    def update_display(self):
        if self.step_index < self.step_count:
            label, body = self.steps[self.step_index]
            self.step_text = "{}\n\n{}".format(label, body)
            self.primary_button_text = "Probe Ring"
        else:
            self.step_text = "Results\n\nReview the measured center shift and correction estimate."
            self.primary_button_text = "Restart"
        self.points_text = self.format_points()

    def format_points(self):
        if not self.points:
            return "No measurements yet"
        lines = []
        for index, point in enumerate(self.points):
            lines.append("{}: X{:.4f} Y{:.4f}".format(self.steps[index][0], point[0], point[1]))
        return "\n".join(lines)

    def on_persist_correction(self, instance, value):
        if value and self.step_index >= self.step_count and self.current_correction is not None:
            self.store_correction(self.current_correction)
        else:
            self.config["enabled"] = "1" if value else "0"
            ConfigUtils.save_config(self.config, self.config_filename)
            self.update_stored_correction_text()
            self.notify_correction_changed()

    def update_stored_correction_text(self):
        if self.config.get("enabled", "0") != "1":
            self.stored_correction_text = "Stored correction: off"
            return
        try:
            x = float(self.config.get("x", "0"))
            y = float(self.config.get("y", "0"))
            self.stored_correction_text = "Stored correction: X{:.4f} Y{:.4f}".format(x, y)
        except ValueError:
            self.stored_correction_text = "Stored correction: invalid"

    def notify_correction_changed(self):
        if self.on_correction_changed is not None:
            self.on_correction_changed()

    def primary_action(self):
        if self.step_index >= self.step_count:
            self.reset()
            return
        self.start_probe()

    def previous_step(self):
        if self.step_index <= 0:
            return
        if len(self.points) >= self.step_index:
            self.points = self.points[:self.step_index - 1]
        self.step_index -= 1
        self.result_text = "Returned to {}.".format(self.steps[self.step_index][0])
        self.update_display()

    def start_probe(self):
        gcode = self.build_probe_gcode()
        if not gcode:
            return
        self.command_text = gcode
        self.is_running = True
        self._waiting_for_probe = True
        self._probe_started_busy = False
        self._probe_poll_count = 0
        self.controller.executeCommand(gcode + "\n")
        Clock.schedule_interval(self.poll_probe_complete, 0.25)

    def build_probe_gcode(self):
        source = self.get_probe_tip_config() or {}
        cfg = {}
        for key in (
                BoreParameterDefinitions.XAxisDistance.code,
                BoreParameterDefinitions.YAxisDistance.code,
                BoreParameterDefinitions.PocketProbeDepth.code,
                BoreParameterDefinitions.FastFeedRate.code,
                BoreParameterDefinitions.RapidFeedRate.code,
                BoreParameterDefinitions.RepeatOperationCount.code,
                BoreParameterDefinitions.EdgeRetractDistance.code,
                BoreParameterDefinitions.QAngle.code,
                BoreParameterDefinitions.BottomSurfaceRetract.code,
                BoreParameterDefinitions.UseProbeNormallyClosed.code):
            if key in source:
                cfg[key] = source[key]
        if self.apply_probe_correction and BoreParameterDefinitions.ProbeTipDiameter.code in source:
            cfg[BoreParameterDefinitions.ProbeTipDiameter.code] = source[BoreParameterDefinitions.ProbeTipDiameter.code]
        cfg[BoreParameterDefinitions.ZeroXYPosition.code] = "0"
        return BoreOperationType.CenterBore.value.generate(cfg)

    def poll_probe_complete(self, dt):
        self._probe_poll_count += 1
        app = App.get_running_app()
        if not app or app.state == NOT_CONNECTED:
            self.is_running = False
            self.result_text = "No connected machine state was detected. Check the connection and restart this step."
            return False
        if app.state not in ("Idle", NOT_CONNECTED):
            self._probe_started_busy = True
            return True
        if not self._probe_started_busy:
            if self._probe_poll_count > 20:
                self.is_running = False
                self.result_text = "Probe did not appear to start. Check the command preview/connection and restart this step."
                return False
            return True
        self.complete_probe_capture()
        return False

    def complete_probe_capture(self):
        if self.is_running:
            Clock.unschedule(self.poll_probe_complete)
        self.is_running = False
        self._waiting_for_probe = False
        point = (float(CNC.vars["wx"]), float(CNC.vars["wy"]))
        if len(self.points) > self.step_index:
            self.points[self.step_index] = point
        else:
            self.points.append(point)
        self.step_index = min(len(self.points), self.step_count)
        self.result_text = "Captured X{:.4f} Y{:.4f}.".format(point[0], point[1])
        if len(self.points) >= self.step_count:
            self.result_text = self.calculate_results()
        self.update_display()

    def calculate_results(self):
        max_shift = 0.0
        max_pair = (0, 0)
        for first in range(len(self.points)):
            for second in range(first + 1, len(self.points)):
                shift = self.distance(self.points[first], self.points[second])
                if shift > max_shift:
                    max_shift = shift
                    max_pair = (first, second)

        lower_bound = max_shift / 2.0
        correction = self.calculate_center_position_correction()
        self.current_correction = correction
        quality_note = self.get_measurement_quality_note(max_shift)
        correction_note = "Probe tip diameter was included in the probing command." if self.apply_probe_correction else "Probe tip diameter was not included in the probing command."
        stored_note = self.store_correction(correction)

        return (
            "Worst center shift: {:.4f} mm ({} to {})\n"
            "Estimated eccentricity lower bound: {:.4f} mm\n"
            "Center-position correction: {}\n"
            "{}\n{}"
            "{}"
        ).format(
            max_shift,
            self.steps[max_pair[0]][0],
            self.steps[max_pair[1]][0],
            lower_bound,
            self.format_correction(correction),
            correction_note,
            quality_note,
            stored_note,
        )

    def calculate_center_position_correction(self):
        if len(self.points) < 3:
            return None
        circle_center = self.average_point(self.points)
        marked_position = self.points[0]
        return (circle_center[0] - marked_position[0], circle_center[1] - marked_position[1])

    def average_point(self, points):
        return (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )

    def format_correction(self, correction):
        if correction is None:
            return "unavailable"
        return "X{:.4f} Y{:.4f}".format(correction[0], correction[1])

    def store_correction(self, correction):
        if not self.persist_correction:
            self.update_stored_correction_text()
            return ""
        self.config["enabled"] = "1"
        self.config["x"] = "{:.6f}".format(correction[0])
        self.config["y"] = "{:.6f}".format(correction[1])
        ConfigUtils.save_config(self.config, self.config_filename)
        self.update_stored_correction_text()
        self.notify_correction_changed()
        return "\nCorrection stored and enabled for future XY-zeroing probe jobs. Align the USB cable to the marked position before probing."

    def get_measurement_quality_note(self, max_shift):
        if len(self.points) < 3 or max_shift <= 0:
            return "Repeat the check if the result is close to your tolerance limit."
        distances = []
        for first in range(len(self.points)):
            for second in range(first + 1, len(self.points)):
                distances.append(self.distance(self.points[first], self.points[second]))
        shortest = min(distances)
        longest = max(distances)
        if longest <= 0:
            return "Repeat the check if the result is close to your tolerance limit."
        if shortest / longest < 0.35:
            return "Result quality: rough. Rotations may not have been close to 120 degrees, but correction was still estimated."
        if max_shift < 0.02:
            return "Result quality: small shift. Correction may be dominated by probe repeatability."
        return "Result quality: usable for a practical drift correction."

    def distance(self, first, second):
        return math.sqrt((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2)

class ProbingPopup(ModalView):

    controller: Controller

    def __init__(self, controller, **kwargs):
        self.outside_corner_settings = None
        self.inside_corner_settings = None
        self.single_axis_settings = None
        self.bore_settings = None
        self.boss_settings = None
        self.angle_settings = None
        self.probeTipSettings = None
        self.calibration_settings = None
        self.fourth_axis_settings = None
        self.controller = controller

        self.preview_popup = ProbingPreviewPopup(controller)
        self.ring_gauge_drift_popup = RingGaugeDriftPopup(
            controller,
            self.get_probe_tip_config,
            on_correction_changed=self.load_ring_gauge_correction)
        self.ring_gauge_correction = {}
        self.load_ring_gauge_correction()

        # wait on UI to finish loading
        Clock.schedule_once(self.delayed_bind, 0.1)

        super(ProbingPopup, self).__init__(**kwargs)

    def open_probe_info_url(self):
        webbrowser.open("https://carvera-community.gitbook.io/docs/firmware/features/3d-probe-support")

    def get_probe_tip_config(self):
        if self.probeTipSettings is None:
            return {}
        return self.probeTipSettings.get_config()

    def open_ring_gauge_drift_popup(self):
        self.ring_gauge_drift_popup.open()

    def load_ring_gauge_correction(self):
        self.ring_gauge_correction = ConfigUtils.load_config(RingGaugeDriftPopup.config_filename)

    def delayed_bind(self, dt):
        self.outside_corner_settings = self.ids.outside_corner_settings
        self.inside_corner_settings = self.ids.inside_corner_settings
        self.single_axis_settings = self.ids.single_axis_settings
        self.bore_settings = self.ids.bore_settings
        self.boss_settings = self.ids.boss_settings
        self.calibration_settings = self.ids.calibration_settings_id
        self.angle_settings = self.ids.angle_settings
        self.probeTipSettings = self.ids.probeTipSettings
        self.fourth_axis_settings = self.ids.fourth_axis_settings

    def delayed_bind_complete(self, dt):
        #self.angle_settings = self.ids.angle_settings
        #self.probeTipSettings = self.ids.probeTipSettings
        return


    def on_single_axis_probing_pressed(self, operation_key: str):
        cfg = self.single_axis_settings.get_config()
        the_op = SingleAxisProbeOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_inside_corner_probing_pressed(self, operation_key: str):
        cfg = self.inside_corner_settings.get_config()
        the_op = InsideCornerOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_outside_corner_probing_pressed(self, operation_key: str):

        cfg = self.outside_corner_settings.get_config()
        the_op = OutsideCornerOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_bore_probing_pressed(self, operation_key: str):

        cfg = self.bore_settings.get_config()
        the_op = BoreOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_boss_probing_pressed(self, operation_key: str):

        cfg = self.boss_settings.get_config()
        the_op = BossOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_angle_probing_pressed(self, operation_key: str):

        cfg = self.angle_settings.get_config()
        the_op = AngleOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_probeTip_probing_pressed(self, operation_key: str):
        cfg = self.probeTipSettings.get_config()
        the_op = ProbeTipOperationType[operation_key].value
        self.show_preview(the_op,cfg)

    def on_callibration_probing_pressed(self, operation_key: str):
        cfg = self.calibration_settings.get_config()
        the_op = CalibrationOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def on_fourth_axis_probing_pressed(self, operation_key: str):
        cfg = self.fourth_axis_settings.get_config()
        the_op = FourthAxisOperationType[operation_key].value
        self.show_preview(the_op, cfg)

    def show_preview(self, operation: OperationsBase, cfg):
        missing_definition = operation.get_missing_config(cfg)

        if missing_definition is None:
            gcode = operation.generate(cfg)
            gcode = self.apply_ring_gauge_correction_to_gcode(gcode, cfg)
            self.preview_popup.gcode = gcode
            self.preview_popup.probe_preview_label = gcode
        else:
            self.preview_popup.gcode = ""
            self.preview_popup.probe_preview_label = "Missing required parameter " + missing_definition.label

        self.preview_popup.open()

        Clock.schedule_once(lambda dt: self.link_shared_data_with_refresh(self.preview_popup), 0.1)

    def apply_ring_gauge_correction_to_gcode(self, gcode, cfg):
        correction = self.ring_gauge_correction
        if correction.get("enabled", "0") != "1":
            return gcode
        if cfg.get("S", "0") == "0":
            return gcode
        if not gcode.startswith(("M461", "M462", "M463", "M464")):
            return gcode
        try:
            correction_x = float(correction.get("x", "0"))
            correction_y = float(correction.get("y", "0"))
        except ValueError:
            return gcode
        if abs(correction_x) < 0.000001 and abs(correction_y) < 0.000001:
            return gcode
        return "{}\nG10L20P0 X{:.4f} Y{:.4f}".format(gcode, -correction_x, -correction_y)

    def link_shared_data_with_refresh(self, popup):
        app = App.get_running_app()
        app.mdi_data.clear()
        try:
            popup.ids.manual_rvPopup.data = app.mdi_data
        except IndexError:
            logger.error('Recycle view layout change ignored')


        app.bind(mdi_data=lambda instance, value: self.on_mdi_data_changed(popup))
    
    def on_mdi_data_changed(self, popup):
        try:
            popup.ids.manual_rvPopup.refresh_from_data()
            Clock.schedule_once(lambda dt: self.scroll_to_bottom(popup.ids.manual_rvPopup), 0.01)
        except Exception as e:
            print("Popup refresh failed:", e)

    def scroll_to_bottom(self, rv):
        try:
            Clock.schedule_once(lambda dt: setattr(rv, 'scroll_y', 0), 0.01)
        except Exception as e:
            print("Scroll failed:", e)
