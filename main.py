import sys
import time
import threading

import json
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.settings import SettingsWithSidebar
from kivy.uix.stencilview import StencilView
from kivy.uix.slider import Slider
from kivy.uix.dropdown import DropDown
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.modalview import ModalView
from kivy.properties import StringProperty
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.label import Label
from kivy.properties import BooleanProperty
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.properties import ObjectProperty, NumericProperty

from serial.tools.list_ports import comports
from functools import partial
from WIFIStream import MachineDetector
from kivy.core.window import Window

import os

import Utils
from kivy.config import Config
from kivy.config import ConfigParser
from CNC import CNC
from GcodeViewer import GCodeViewer
from Controller import Controller, NOT_CONNECTED, STATECOLOR, STATECOLORDEF, HALT_REASON,\
    LOAD_DIR, LOAD_FILE, LOAD_MV, LOAD_RM, LOAD_MKDIR, SEND_FILE, LOAD_MD5, LOAD_WIFI, LOAD_CONN_WIFI, CONN_USB, CONN_WIFI, LOAD_CONFIG

Config.set('graphics', 'width', '960')
Config.set('graphics', 'height', '600')
Config.write()

Window.softinput_mode = "below_target"

_device     = None
_baud       = None

SHORT_LOAD_TIMEOUT = 1  # s
WIFI_LOAD_TIMEOUT = 20 # s
CONFIG_LOAD_TIMEOUT = 5 # s
LONG_LOAD_TIMEOUT  = 60  # s
HEARTBEAT_TIMEOUT = 2

MAX_TOUCH_INTERVAL = 0.15
GCODE_VIEW_SPEED = 1

class GcodePlaySlider(Slider):
    def on_touch_down(self, touch):
        released = super(GcodePlaySlider, self).on_touch_down(touch)
        if released and self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance/ 1000)
            return True
        return released

    def on_touch_move(self, touch):
        released = super(GcodePlaySlider, self).on_touch_move(touch)
        if self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance/ 1000)
            # float_number = self.value * app.root.selected_file_line_count / 1000
            # app.root.gcode_viewer.set_distance_by_lineidx(int(float_number), float_number - int(float_number))
            return True
        return released

class FloatBox(FloatLayout):
    touch_interval = 0

    def on_touch_down(self, touch):
        if super(FloatBox, self).on_touch_down(touch):
            return True

        if self.collide_point(*touch.pos) and not self.gcode_ctl_bar.collide_point(*touch.pos):
            if 'button' in touch.profile and touch.button == 'left':
                    self.touch_interval =  time.time()

    def on_touch_up(self, touch):
        if super(FloatBox, self).on_touch_up(touch):
            return True

        app = App.get_running_app()
        if self.collide_point(*touch.pos) and not self.gcode_ctl_bar.collide_point(*touch.pos):
            if 'button' in touch.profile and touch.button == 'left':
                if time.time() - self.touch_interval < MAX_TOUCH_INTERVAL:
                    app.show_gcode_ctl_bar = not app.show_gcode_ctl_bar

class BoxStencil(BoxLayout, StencilView):
    pass

class ConfirmPopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super(ConfirmPopup, self).__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False


class MessagePopup(ModalView):
    def __init__(self, **kwargs):
        super(MessagePopup, self).__init__(**kwargs)

class InputPopup(ModalView):
    cache_var1 = StringProperty('')
    cache_var2 = StringProperty('')
    cache_var3 = StringProperty('')
    def __init__(self, **kwargs):
        super(InputPopup, self).__init__(**kwargs)

class ProgressPopup(ModalView):
    progress_text = StringProperty('')
    progress_value = NumericProperty('0')

    def __init__(self, **kwargs):
        super(ProgressPopup, self).__init__(**kwargs)

class OriginPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(OriginPopup, self).__init__(**kwargs)

class ZProbePopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(ZProbePopup, self).__init__(**kwargs)

class ManualZProbePopup(ModalView):
    def __init__(self, **kwargs):
        super(ManualZProbePopup, self).__init__(**kwargs)

class AutoLevelPopup(ModalView):
    execute = False

    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(AutoLevelPopup, self).__init__(**kwargs)

    def init(self):
        x_steps = int(self.sp_x_points.text)
        y_steps = int(self.sp_y_points.text)
        self.lb_min_x.text = "{:.2f}".format(CNC.vars['xmin'])
        self.lb_max_x.text = "{:.2f}".format(CNC.vars['xmax'])
        self.lb_step_x.text = "{:.2f}".format((CNC.vars['xmax'] - CNC.vars['xmin']) * 1.0 / x_steps)
        self.lb_min_y.text = "{:.2f}".format(CNC.vars['ymin'])
        self.lb_max_y.text = "{:.2f}".format(CNC.vars['ymax'])
        self.lb_step_y.text = "{:.2f}".format((CNC.vars['ymax'] - CNC.vars['ymin']) * 1.0 / y_steps)

    def init_and_open(self, execute = False):
        self.execute = execute
        self.init()
        self.open()

class FilePopup(ModalView):
    def __init__(self, **kwargs):
        super(FilePopup, self).__init__(**kwargs)

    # -----------------------------------------------------------------------
    def load_remote_root(self):
        self.remote_rv.child_dir('')

    # -----------------------------------------------------------------------
    def update_local_buttons(self):
        has_select = False
        app = App.get_running_app()
        for key in self.local_rv.view_adapter.views:
            if self.local_rv.view_adapter.views[key].selected and not self.local_rv.view_adapter.views[key].selected_dir:
               has_select = True
               break
        self.btn_open.disabled = not has_select
        self.btn_upload.disabled = not has_select or app.state != 'Idle'

    # -----------------------------------------------------------------------
    def update_remote_buttons(self):
        has_select = False
        select_dir = False
        for key in self.remote_rv.view_adapter.views:
            if self.remote_rv.view_adapter.views[key].selected:
                has_select = True
                if self.remote_rv.view_adapter.views[key].selected_dir:
                    select_dir = True
                break
        self.btn_delete.disabled = not has_select
        self.btn_rename.disabled = not has_select
        self.btn_select.disabled = (not has_select) or select_dir

class CoordPopup(ModalView):
    config = {}
    origin_popup = ObjectProperty()
    zprobe_popup = ObjectProperty()
    auto_level_popup = ObjectProperty()

    def __init__(self, config, **kwargs):
        self.config = config
        self.origin_popup = OriginPopup(self)
        self.zprobe_popup = ZProbePopup(self)
        self.auto_level_popup = AutoLevelPopup(self)
        super(CoordPopup, self).__init__(**kwargs)

    def set_config(self, key1, key2, value):
        self.config[key1][key2] = value
        self.cnc_workspace.draw()

    def load_config(self):
        self.cnc_workspace.load_config(self.config)
        self.cnc_workspace.draw()

        # init origin popup
        self.origin_popup.cbx_anchor1.active = self.config['origin']['anchor'] == 1
        self.origin_popup.cbx_anchor2.active = self.config['origin']['anchor'] == 2
        self.origin_popup.txt_x_offset.text = str(self.config['origin']['x_offset'])
        self.origin_popup.txt_y_offset.text = str(self.config['origin']['y_offset'])

        self.load_origin_label()

        # init zprobe widgets

        self.cbx_zprobe.active = self.config['zprobe']['active']
        # init zprobe popup
        self.zprobe_popup.cbx_origin1.active = self.config['zprobe']['origin'] == 1
        self.zprobe_popup.cbx_origin2.active = self.config['zprobe']['origin'] == 2
        self.zprobe_popup.txt_x_offset.text = str(self.config['zprobe']['x_offset'])
        self.zprobe_popup.txt_y_offset.text = str(self.config['zprobe']['y_offset'])

        self.load_zprobe_label()

        # init leveling widgets
        self.cbx_leveling.active = self.config['leveling']['active']
        self.auto_level_popup.sp_x_points.text = str(self.config['leveling']['x_points'])
        self.auto_level_popup.sp_y_points.text = str(self.config['leveling']['y_points'])
        self.load_leveling_label()


    def load_origin_label(self):
        # init origin widgets
        self.lb_origin.text = '(%g, %g) from M Origin' % (CNC.vars['wcox'], CNC.vars['wcoy'])

    def load_zprobe_label(self):
        self.lb_zprobe.text = '(%d, %d) from %s' % (self.config['zprobe']['x_offset'], \
                                                    self.config['zprobe']['y_offset'], \
                                                    'Work Origin' if self.config['zprobe']['origin'] == 1 else 'Path Origin')

    def load_leveling_label(self):
        self.lb_leveling.text = 'X Points: %d, Y Points: %d' % (self.config['leveling']['x_points'], \
                                                    self.config['leveling']['y_points'])

    def toggle_config(self):
        # upldate main status
        app = App.get_running_app()
        app.root.update_coord_config()

class DiagnosePopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super(DiagnosePopup, self).__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False

class ConfigPopup(ModalView):
    def __init__(self, **kwargs):
        super(ConfigPopup, self).__init__(**kwargs)

    def on_open(self):
        pass

    def on_dismiss(self):
        pass

class MakeraConfigPanel(SettingsWithSidebar):
    def on_config_change(self, config, section, key, value):
        app = App.get_running_app()
        if section != 'Restore':
            app.root.controller.setConfigValue(key, Utils.to_config(app.root.setting_type_list[key], value))
        elif key == 'restore' and value == 'RESTORE':
            app.root.controller.restoreConfigCommand()

class XDropDown(DropDown):
    pass

class YDropDown(DropDown):
    pass

class ZDropDown(DropDown):
    pass

class ADropDown(DropDown):
    pass

class FeedDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False

class SpindleDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False

class ToolDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False

class LaserDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class FuncDropDown(DropDown):
    pass

class StatusDropDown(DropDown):
    def __init__(self, **kwargs):
        super(StatusDropDown, self).__init__(**kwargs)

class ComPortsDropDown(DropDown):
    def __init__(self, **kwargs):
        super(DropDown, self).__init__(**kwargs)


class OperationDropDown(DropDown):
    pass

class MachineButton(Button):
    ip = StringProperty("")
    port = NumericProperty(2222)
    busy = BooleanProperty(False)

class IconButton(BoxLayout, Button):
    icon = StringProperty("fresk.png")

class TransparentButton(BoxLayout, Button):
    icon = StringProperty("fresk.png")

class WiFiButton(BoxLayout, Button):
    ssid = StringProperty("")
    encrypted = BooleanProperty(False)
    strength = NumericProperty(1000)
    connected = BooleanProperty(False)

class CNCWorkspace(Widget):
    config = {}

    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        self.bind(size=self.on_draw)
        super(CNCWorkspace, self).__init__(**kwargs)

    def load_config(self, config):
        self.config = config

    def draw(self):
        if self.x <= 100:
            return
        self.canvas.clear()
        zoom = self.width / CNC.vars['worksize_x']
        with self.canvas:
            # background
            Color(50 / 255, 50 / 255, 50 / 255, 1)
            Rectangle(pos=self.pos, size=self.size)

            # anchor1
            if self.config['origin']['anchor'] == 1:
                Color(75 / 255, 75 / 255, 75 / 255, 1)
            else:
                Color(55 / 255, 55 / 255, 55 / 255, 1)
            Rectangle(pos=(self.x + (CNC.vars['anchor1_x'] - CNC.vars['anchor_width'] - CNC.vars['edge_x']) * zoom, self.y + (CNC.vars['anchor1_y'] - CNC.vars['anchor_width'] - CNC.vars['edge_y']) * zoom),
                      size=(CNC.vars['anchor_length'] * zoom, CNC.vars['anchor_width'] * zoom))
            Rectangle(pos=(self.x + (CNC.vars['anchor1_x'] - CNC.vars['anchor_width'] - CNC.vars['edge_x']) * zoom, self.y + (CNC.vars['anchor1_y'] - CNC.vars['anchor_width'] - CNC.vars['edge_y']) * zoom),
                      size=(CNC.vars['anchor_width'] * zoom, CNC.vars['anchor_length'] * zoom))

            # anchor2
            if self.config['origin']['anchor'] == 2:
                Color(75 / 255, 75 / 255, 75 / 255, 1)
            else:
                Color(55 / 255, 55 / 255, 55 / 255, 1)
            Rectangle(pos=(self.x + (CNC.vars['anchor2_x'] - CNC.vars['anchor_width'] - CNC.vars['edge_x']) * zoom, self.y + (CNC.vars['anchor2_y'] - CNC.vars['anchor_width'] - CNC.vars['edge_y']) * zoom),
                      size=(CNC.vars['anchor_length'] * zoom, CNC.vars['anchor_width'] * zoom))
            Rectangle(pos=(self.x + (CNC.vars['anchor2_x'] - CNC.vars['anchor_width'] - CNC.vars['edge_x']) * zoom, self.y + (CNC.vars['anchor2_y'] - CNC.vars['anchor_width'] - CNC.vars['edge_y']) * zoom),
                      size=(CNC.vars['anchor_width'] * zoom, CNC.vars['anchor_length'] * zoom))

            # origin
            Color(52/255, 152/255, 219/255, 1)
            origin_x = CNC.vars['wcox'] - CNC.vars['edge_x']
            origin_y = CNC.vars['wcoy'] - CNC.vars['edge_y']
            Ellipse(pos=(self.x + origin_x * zoom - 12.5, self.y + origin_y * zoom - 12.5), size=(25, 25))

            # work area
            Color(0, 0.8, 0, 1)
            Line(width=1, rectangle=(self.x + (origin_x + CNC.vars['xmin']) * zoom, self.y + (origin_y + CNC.vars['ymin']) * zoom,
                                     (CNC.vars['xmax'] - CNC.vars['xmin']) * zoom, (CNC.vars['ymax'] - CNC.vars['ymin']) * zoom))

            # z probe
            if self.config['zprobe']['active']:
                Color(231/255, 76/255, 60/255, 1)
                zprobe_x = self.config['zprobe']['x_offset'] + (origin_x if self.config['zprobe']['origin'] == 1 else origin_x + CNC.vars['xmin'])
                zprobe_y = self.config['zprobe']['y_offset'] + (origin_y if self.config['zprobe']['origin'] == 1 else origin_y + CNC.vars['ymin'])
                Ellipse(pos=(self.x + zprobe_x * zoom - 10, self.y + zprobe_y * zoom - 10), size=(20, 20))

            # auto leveling
            if self.config['leveling']['active']:
                Color(244/255, 208/255, 63/255, 1)
                for x in Utils.xfrange(0.0, CNC.vars['xmax'] - CNC.vars['xmin'], self.config['leveling']['x_points']):
                    for y in Utils.xfrange(0.0, CNC.vars['ymax'] - CNC.vars['ymin'], self.config['leveling']['y_points']):
                        Ellipse(pos=(self.x + (origin_x + CNC.vars['xmin'] + x) * zoom - 7.5, self.y + (origin_y + CNC.vars['ymin'] + y) * zoom - 7.5), size=(15, 15))
                        # print('x=%f, y=%f' % (x, y))


    def on_draw(self, obj, value):
        self.draw()




class SelectableRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior,
                                 RecycleBoxLayout):
    ''' Adds selection and focus behaviour to the view. '''

class TopDataView(BoxLayout, Button):
    pass

class SelectableLabel(RecycleDataViewBehavior, Label):
    ''' Add selection support to the Label '''
    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        ''' Catch and handle the view changes '''
        self.index = index
        return super(SelectableLabel, self).refresh_view_attrs(
            rv, index, data)

    def on_touch_down(self, touch):
        ''' Add selection on touch down '''
        if super(SelectableLabel, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        ''' Respond to the selection of items in the view. '''
        self.selected = is_selected

class SelectableBoxLayout(RecycleDataViewBehavior, BoxLayout):
    ''' Add selection support to the Label '''
    index = None
    selected = BooleanProperty(False)
    selected_dir = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        ''' Catch and handle the view changes '''
        self.index = index
        return super(SelectableBoxLayout, self).refresh_view_attrs(
            rv, index, data)

    def on_touch_down(self, touch):
        ''' Add selection on touch down '''
        if super(SelectableBoxLayout, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            if touch.is_double_tap:
                rv = self.parent.recycleview
                if rv.data[self.index]['is_dir']:
                    rv.child_dir(rv.data[self.index]['filename'])
                return True
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        ''' Respond to the selection of items in the view. '''
        self.selected = is_selected
        if self.selected:
            if rv.data[self.index]['is_dir']:
                self.selected_dir = True
            else:
                self.selected_dir = False
            rv.set_curr_selected_file(rv.data[self.index]['filename'], rv.data[self.index]['intsize'])
            rv.dispatch('on_select')

# -----------------------------------------------------------------------
# Remote Recycle View
# -----------------------------------------------------------------------
class RemoteRV(RecycleView):
    base_dir = '/sd/gcodes'
    curr_dir = base_dir
    curr_dir_name = StringProperty('  Root')
    curr_selected_file = ''
    curr_selected_filesize = 0

    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        super(RemoteRV, self).__init__(**kwargs)
        self.register_event_type('on_select')

    def set_curr_selected_file(self, filename, filesize):
        self.curr_selected_file =  os.path.join(self.curr_dir, filename)
        self.curr_selected_filesize = filesize

    # -----------------------------------------------------------------------
    def on_select(self):
        pass

    # -----------------------------------------------------------------------
    def clear_selection(self):
        for i in range(len(self.view_adapter.views)):
            if self.view_adapter.views[i].selected != None:
                self.view_adapter.views[i].selected = False

    # -----------------------------------------------------------------------
    def child_dir(self, child_dir):
        new_path = os.path.join(self.curr_dir, child_dir)
        self.list_dir(new_path)

    # -----------------------------------------------------------------------
    def parent_dir(self):
        normpath = os.path.normpath(self.curr_dir)
        if normpath == self.base_dir:
            self.list_dir(normpath)
        else:
            self.list_dir(os.path.dirname(normpath))

    # -----------------------------------------------------------------------
    def current_dir(self, *args):
        self.list_dir(os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir):
        self.clear_selection()
        self.data = []

        app = App.get_running_app()
        app.root.loadRemoteDir(new_dir)
        self.curr_dir = str(new_dir)
        if os.path.normpath(self.curr_dir) == self.base_dir:
            self.curr_dir_name = '  Root'
        else:
            self.curr_dir_name ='  < ' + os.path.basename(os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def fill_dir(self, dirs, files):
        self.data = []
        rv_key = 0
        for dir_name in dirs:
            if not dir_name.startswith('.'):
                self.data.append({'rv_key': rv_key, 'filename': dir_name, 'intsize': 0, 'filesize': '', 'is_dir': True})
                rv_key += 1
        for file_name, file_size in files:
            if not file_name.startswith('.'):
                self.data.append({'rv_key': rv_key, 'filename': file_name, 'intsize': int(file_size), 'filesize': Utils.humansize(file_size), 'is_dir': False})
                rv_key += 1
        # trigger
        self.dispatch('on_select')

# -----------------------------------------------------------------------
# Local Recycle View
# -----------------------------------------------------------------------
class LocalRV(RecycleView):
    curr_dir = os.path.abspath('./gcodes')
    curr_dir_name = StringProperty('  < ' + os.path.basename(os.path.normpath(curr_dir)))
    curr_selected_file = ''
    curr_selected_filesize = 0

    def __init__(self, **kwargs):
        super(LocalRV, self).__init__(**kwargs)
        self.register_event_type('on_select')

    # -----------------------------------------------------------------------
    def set_curr_selected_file(self, filename, filesize):
        self.curr_selected_file =  os.path.join(self.curr_dir, filename)
        self.curr_selected_filesize = filesize

    # -----------------------------------------------------------------------
    def on_select(self):
        pass

    # -----------------------------------------------------------------------
    def clear_selection(self):
        for key in self.view_adapter.views:
            if self.view_adapter.views[key].selected != None:
                self.view_adapter.views[key].selected = False

    # -----------------------------------------------------------------------
    def child_dir(self, child_dir):
        new_path = os.path.join(self.curr_dir, child_dir)
        self.list_dir(new_path)

    # -----------------------------------------------------------------------
    def parent_dir(self):
        self.list_dir(os.path.abspath(os.path.join(self.curr_dir, os.pardir)))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir):
        self.clear_selection()
        self.data = []
        rv_key = 0
        dirs = []
        files = []
        for (dirpath, dirnames, filenames) in os.walk(new_dir):
            dirs.extend(dirnames)
            files.extend(filenames)
            break
        for dir_name in sorted(dirs):
            if not dir_name.startswith('.'):
                self.data.append({'rv_key': rv_key, 'filename': dir_name, 'intsize': 0, 'filesize': '', 'is_dir': True})
                rv_key += 1
        for file_name in sorted(files):
            if not file_name.startswith('.'):
                file_size = os.stat(os.path.join(new_dir, file_name)).st_size
                self.data.append({'rv_key': rv_key, 'filename': file_name, 'intsize': file_size, 'filesize':\
                    Utils.humansize(file_size), 'is_dir': False})
                rv_key += 1

        self.curr_dir = str(new_dir)
        self.curr_dir_name = '  < ' + os.path.basename(os.path.normpath(self.curr_dir))

        # trigger
        self.dispatch('on_select')

# -----------------------------------------------------------------------
# GCode Recycle View
# -----------------------------------------------------------------------
class GCodeRV(RecycleView):
    data_length = 0
    scroll_time = 0
    old_selected_index = 0
    new_selected_index = 0

    def __init__(self, **kwargs):
        super(GCodeRV, self).__init__(**kwargs)

    def on_scroll_stop(self, touch):
        super(GCodeRV, self).on_scroll_stop(touch)
        self.scroll_time = time.time()

    def select_line(self, *args):
        old_line = self.view_adapter.get_visible_view(self.old_selected_index)
        new_line = self.view_adapter.get_visible_view(self.new_selected_index)
        if old_line:
            old_line.selected = False
        if new_line:
            new_line.selected = True
            self.old_selected_index = self.new_selected_index

    def set_selected(self, index):
        if index != self.old_selected_index:
            if self.data_length > 0 and index < self.data_length:
                page_lines = len(self.view_adapter.views)
                self.new_selected_index = index
                Clock.schedule_once(self.select_line, 0)
                if time.time() - self.scroll_time > 3:
                    scroll_value = Utils.translate(index + 1, page_lines / 2 - 1, self.data_length -  page_lines / 2 + 1, 1.0, 0.0)
                    if scroll_value < 0:
                        scroll_value = 0
                    if scroll_value > 1:
                        scroll_value = 1
                    self.scroll_y = scroll_value

# -----------------------------------------------------------------------
# Manual Recycle View
# -----------------------------------------------------------------------
class ManualRV(RecycleView):

    def __init__(self, **kwargs):
        super(ManualRV, self).__init__(**kwargs)


class TopBar(BoxLayout):
    pass

class BottomBar(BoxLayout):
    pass

# -----------------------------------------------------------------------
class Content(ScreenManager):
    pass

# Declare both screens
class FilePage(Screen):
    pass

class ControlPage(Screen):
    pass

class SettingPage(Screen):
    pass

# -----------------------------------------------------------------------
class CMDManager(ScreenManager):
    pass

class GCodeCMDPage(Screen):
    pass

class ManualCMDPage(Screen):
    pass

# -----------------------------------------------------------------------
class PopupManager(ScreenManager):
    pass

class RemotePage(Screen):
    pass

class LocalPage(Screen):
    pass

class Makera(BoxLayout):
    holding = 0

    loading_file = False
    stop = threading.Event()
    machine_detector = MachineDetector()
    file_popup = ObjectProperty()
    coord_popup = ObjectProperty()
    diagnose_popup = ObjectProperty()
    config_popup = ObjectProperty()
    x_drop_down = ObjectProperty()
    y_drop_down = ObjectProperty()
    z_drop_down = ObjectProperty()
    a_drop_down = ObjectProperty()

    feed_drop_down = ObjectProperty()
    spindle_drop_down = ObjectProperty()
    tool_drop_down = ObjectProperty()
    laser_drop_down = ObjectProperty()
    func_drop_down = ObjectProperty()
    status_drop_down = ObjectProperty()

    operation_drop_down = ObjectProperty()

    confirm_popup = ObjectProperty()
    message_popup = ObjectProperty()
    progress_popup = ObjectProperty()
    input_popup = ObjectProperty()

    gcode_viewer = ObjectProperty()
    gcode_playing = BooleanProperty(False)

    coord_config = {}

    progress_info = StringProperty()
    selected_file_line_count = NumericProperty(0)

    test_line = NumericProperty(1)

    config_loaded = False
    setting_list = {}
    setting_type_list = {}

    gcode_viewer_distance = 0

    alarm_triggered = False

    played_lines = 0

    control_list = {
        # 'control_name: [update_time, value]'
        'feedrate_scale':     [0.0, 100],
        'spindle_scale':      [0.0, 100],
        'laser_mode':         [0.0, 0],
        'laser_scale':        [0.0, 100],
        'laser_test':         [0.0, 0],
        'spindle_switch':     [0.0, 0],
        'spindle_slider':     [0.0, 0],
        'spindlefan_switch':  [0.0, 0],
        'spindlefan_slider':  [0.0, 0],
        'vacuum_switch':      [0.0, 0],
        'vacuum_slider':      [0.0, 0],
        'laser_switch':       [0.0, 0],
        'laser_slider':       [0.0, 0],
        'light_switch':       [0.0, 0],
        'tool_sensor_switch': [0.0, 0]
    }

    status_index = 0

    def __init__(self):
        super(Makera, self).__init__()
        self.file_popup = FilePopup()

        self.cnc = CNC()
        self.controller = Controller(self.cnc, self.execCallback)
        # Fill basic global variables
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[NOT_CONNECTED]

        self.coord_config = {
            'origin': {
                'anchor': 2,
                'x_offset': 0,
                'y_offset': 0
            },
            'zprobe': {
                'active': True,
                'origin': 2,
                'x_offset': 10,
                'y_offset': 10
            },
            'leveling': {
                'active': False,
                'x_points': 5,
                'y_points': 5
            }
        }
        self.update_coord_config()
        self.coord_popup = CoordPopup(self.coord_config)
        self.manual_zprobe_popup = ManualZProbePopup()

        self.diagnose_popup = DiagnosePopup()

        self.x_drop_down = XDropDown()
        self.y_drop_down = YDropDown()
        self.z_drop_down = ZDropDown()
        self.a_drop_down = ADropDown()
        self.feed_drop_down = FeedDropDown()
        self.spindle_drop_down = SpindleDropDown()
        self.tool_drop_down = ToolDropDown()
        self.laser_drop_down = LaserDropDown()
        self.func_drop_down = FuncDropDown()
        self.status_drop_down = StatusDropDown()
        #
        self.operation_drop_down = OperationDropDown()
        #
        self.confirm_popup = ConfirmPopup()
        self.message_popup = MessagePopup()
        self.progress_popup = ProgressPopup()
        self.input_popup = InputPopup()

        self.comports_drop_down = DropDown(auto_width=False, width=500)
        self.wifi_conn_drop_down = DropDown(auto_width=False, width=500)

        self.wifi_ap_drop_down = DropDown(auto_width=False, width=600)
        self.wifi_ap_drop_down.bind(on_select=lambda instance, x: self.connWIFI(x))
        self.wifi_ap_status_bar = None

        # init gcode viewer
        self.gcode_viewer = GCodeViewer()
        self.gcode_viewer_container.add_widget(self.gcode_viewer)
        self.gcode_viewer.set_frame_callback(self.gcode_play_call_back)

        # init settings
        self.config = ConfigParser()
        self.config_popup = ConfigPopup()
        self.config_loaded = False
        self.setting_list = {}
        self.setting_type_list = {}

        self.usb_event = lambda instance, x: self.openUSB(x)
        self.wifi_event = lambda instance, x: self.openWIFI(x)

        self.heartbeat_time = 0

        # blink timer
        Clock.schedule_interval(self.blink_state, 0.5)
        # status switch timer
        Clock.schedule_interval(self.switch_status, 8)

        #
        threading.Thread(target=self.monitorSerial).start()

    # -----------------------------------------------------------------------
    def play(self, file_name):
        zprobed = False
        autolevel = False
        if self.coord_config['zprobe']['active']:
            zprobed = True
        if self.coord_config['leveling']['active']:
            autolevel = True
        if zprobed and autolevel:
            self.execute_probelevel(self.coord_config['zprobe']['origin'], self.coord_config['zprobe']['x_offset'],
                                    self.coord_config['zprobe']['y_offset'], self.coord_config['leveling']['x_points'],
                                   self.coord_config['leveling']['y_points'], True)
        elif zprobed:
            self.execute_zprobe(self.coord_config['zprobe']['origin'], self.coord_config['zprobe']['x_offset'],
                           self.coord_config['zprobe']['y_offset'], True)
        elif autolevel:
            self.execute_autolevel(self.coord_config['leveling']['x_points'],
                                   self.coord_config['leveling']['y_points'], True)

        self.controller.playCommand(file_name)

    # -----------------------------------------------------------------------
    def execute_zprobe(self, origin, offset_x, offset_y, buffer = False):
        if origin == 1:
            self.controller.gotoPosition("Work Origin", offset_x, offset_y, True, buffer)
        elif origin == 2:
            self.controller.gotoPosition("Path Origin", offset_x, offset_y, True, buffer)
        self.controller.zProbeCommand(buffer)

    # -----------------------------------------------------------------------
    def execute_autolevel(self, x_points, y_points, buffer = False):
        self.controller.autoLevelCommand(x_points, y_points, buffer)

    # -----------------------------------------------------------------------
    def execute_probelevel(self, origin, offset_x, offset_y, x_points, y_points, buffer = False):
        if origin == 1:
            self.controller.gotoPosition("Work Origin", offset_x, offset_y, True, buffer)
        elif origin == 2:
            self.controller.gotoPosition("Path Origin", offset_x, offset_y, True, buffer)

        self.controller.probeLevelCommand(x_points, y_points, buffer)

    # -----------------------------------------------------------------------
    def set_work_origin(self):
        origin_x = self.coord_config['origin']['x_offset']
        origin_y = self.coord_config['origin']['y_offset']
        if self.coord_config['origin']['anchor'] == 1:
            origin_x += CNC.vars['anchor1_x']
            origin_y += CNC.vars['anchor1_y']
        else:
            origin_x += CNC.vars['anchor2_x']
            origin_y += CNC.vars['anchor2_y']

        self.controller.wcsSetM(origin_x, origin_y, None, None)

        # refresh after 1 seconds
        Clock.schedule_once(self.refresh_work_origin, 1)


    # -----------------------------------------------------------------------
    def refresh_work_origin(self, *args):
        self.coord_popup.load_config()

    # -----------------------------------------------------------------------
    def blink_state(self, *args):
        if self.holding == 1:
            self.status_data_view.color = STATECOLOR['Hold']
            self.holding = 2
        elif self.holding == 2:
            self.status_data_view.color = STATECOLOR['Disable']
            self.holding = 1

        # check heartbeat
        if self.controller.sendNUM != 0 or self.controller.loadNUM != 0 or self.loading_file:
            self.heartbeat_time = time.time()

        if time.time() - self.heartbeat_time > HEARTBEAT_TIMEOUT and self.controller.stream:
            self.controller.close()
            self.controller.log.put((Controller.MSG_ERROR, 'ALARM: Connection lost!'))
            self.updateStatus()

    # -----------------------------------------------------------------------
    def switch_status(self, *args):
        self.status_index = self.status_index + 1
        if self.status_index >= 6:
            self.status_index = 0

    # -----------------------------------------------------------------------
    def open_comports_drop_down(self, button):
        self.comports_drop_down.clear_widgets()
        devices = sorted([x[0] for x in comports()])
        for device in devices:
            btn = Button(text=device, size_hint_y=None, height=70)
            btn.bind(on_release=lambda btn: self.comports_drop_down.select(btn.text))
            self.comports_drop_down.add_widget(btn)
        self.comports_drop_down.unbind(on_select=self.usb_event)
        self.comports_drop_down.bind(on_select=self.usb_event)
        self.comports_drop_down.open(button)

    # -----------------------------------------------------------------------
    def open_wifi_conn_drop_down(self, button):
        self.wifi_conn_drop_down.clear_widgets()
        btn = MachineButton(text='Searching nearby machines...', size_hint_y=None, height=70, color=(180 / 255, 180 / 255, 180 / 255, 1))
        self.wifi_conn_drop_down.add_widget(btn)
        self.wifi_conn_drop_down.open(button)
        Clock.schedule_once(self.load_machine_list, 0)

    def load_machine_list(self, *args):
        self.wifi_conn_drop_down.clear_widgets()
        machines = self.machine_detector.get_machine_list()
        if len(machines) == 0:
            btn = MachineButton(text='No found, power on machine first!', size_hint_y=None, height=70,
                                color=(180 / 255, 180 / 255, 180 / 255, 1))
            self.wifi_conn_drop_down.add_widget(btn)
        else:
            for machine in machines:
                btn = MachineButton(text=machine['machine']+('(Busy)' if machine['busy'] else ''), ip=machine['ip'], port=machine['port'], size_hint_y=None, height=70)
                btn.bind(on_release=lambda btn: self.wifi_conn_drop_down.select(btn.ip + ':' + str(btn.port)))
                self.wifi_conn_drop_down.add_widget(btn)
                self.wifi_conn_drop_down.unbind(on_select=self.wifi_event)
                self.wifi_conn_drop_down.bind(on_select=self.wifi_event)


    # -----------------------------------------------------------------------
    def update_coord_config(self):
        self.wpb_zprobe.width = 100 if self.coord_config['zprobe']['active'] else 0
        self.wpb_leveling.width = 100 if self.coord_config['leveling']['active'] else 0

    # -----------------------------------------------------------------------
    # Inner loop to catch any generic exception
    # -----------------------------------------------------------------------
    def monitorSerial(self):
        while not self.stop.is_set():
            t = time.time()

            while self.controller.log.qsize() > 0:
                try:
                    msg, line = self.controller.log.get_nowait()
                    line = line.rstrip("\n")
                    line = line.rstrip("\r")

                    if msg == Controller.MSG_NORMAL:
                        self.manual_rv.data.append({'text': line, 'color': (103/255, 150/255, 186/255, 1)})
                    elif msg == Controller.MSG_ERROR:
                        self.manual_rv.data.append({'text': line, 'color': (250/255, 105/255, 102/255, 1)})
                except:
                    break

            # Update position if needed
            if self.controller.posUpdate:
                Clock.schedule_once(self.updateStatus, 0)
                self.controller.posUpdate = False

            # change diagnose status
            self.controller.diagnosing = self.diagnose_popup.showing
            # update diagnose if needed
            if self.controller.diagnoseUpdate:
                Clock.schedule_once(self.updateDiagnose, 0)
                self.controller.diagnoseUpdate = False

            if self.controller.loadNUM == LOAD_DIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error loading dir \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout loading dir \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.fillRemoteDir, 0)
            if self.controller.loadNUM == LOAD_RM:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error deleting \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout deleting \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MV:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error renaming \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout renaming \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MKDIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error making dir: \'%s\'!' % (self.input_popup.txt_content.text.strip())), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout making dir: \'%s\'!' % (self.input_popup.txt_content.text.strip())), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MD5:
                if self.controller.loadEOF or self.controller.loadERR or t - self.long_load_time > LONG_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error getting md5: \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.long_load_time > LONG_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout getting md5: \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishCompareFileMD5, 0)
            if self.controller.loadNUM == LOAD_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadWiFiError, 'Error getting WiFi info!'), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadWiFiError, 'Timeout getting WiFi info!'), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadWiFi, 0)
            if self.controller.loadNUM == LOAD_CONN_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadConnWiFiError, ''), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadConnWiFiError, 'Timeout connecting WiFi!'), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadConnWiFi, 0)
            if self.controller.loadNUM == LOAD_CONFIG:
                if self.controller.loadEOF or self.controller.loadERR or t - self.config_load_time > CONFIG_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, 'Error loading config!', 0))
                    elif t - self.config_load_time > CONFIG_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout loading config!', 0))
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadConfig, 0)
            elif self.controller.loadNUM == LOAD_FILE:
                if self.controller.loadEOF or self.controller.loadERR or t - self.long_load_time > LONG_LOAD_TIMEOUT:
                    if self.controller.loadEOF:
                        Clock.schedule_once(self.writeLocalFile, 0)
                    elif self.controller.loadERR:
                        if not self.controller.loadCANCEL:
                            Clock.schedule_once(partial(self.loadError, 'Error caching \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                        else:
                            Clock.schedule_once(self.finishCancelCacheFile, 0)
                    elif t - self.long_load_time > LONG_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, 'Timeout caching \'%s\'!' % (self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    self.controller.loadCANCEL = False
                    self.controller.loadCANCELSENT = False
                else:
                    Clock.schedule_once(self.updateCachingProgress, 0)
            elif self.controller.sendNUM == SEND_FILE:
                if self.controller.sendEOF:
                    self.controller.sendNUM = 0
                    self.controller.sendEOF = False
                    self.controller.sendERR = False
                    Clock.schedule_once(self.finishUploadProgress, 0)
                else:
                    Clock.schedule_once(self.updateUploadProgress, 0)

            time.sleep(0.1)

    # -----------------------------------------------------------------------
    def open_del_confirm_popup(self):
        self.confirm_popup.lb_title.text = 'Delete File or Dir'
        self.confirm_popup.lb_content.text = 'Confirm to delete file or dir \'%s\'?' % (self.file_popup.remote_rv.curr_selected_file)
        self.confirm_popup.confirm = partial(self.removeRemoteFile, self.file_popup.remote_rv.curr_selected_file)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_halt_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        if CNC.vars["halt_reason"] in HALT_REASON:
            self.confirm_popup.lb_title.text = 'Machine Is Halted: %s' % (HALT_REASON[CNC.vars["halt_reason"]])
        else:
            self.confirm_popup.lb_title.text = 'Machine Is Halted!'
        if CNC.vars["halt_reason"] > 10:
            self.confirm_popup.lb_content.text = 'Confirm to reset machine?'
            self.confirm_popup.confirm = partial(self.resetMachine)
        else:
            self.confirm_popup.lb_content.text = 'Confirm to unlock machine?'
            self.confirm_popup.confirm = partial(self.unlockMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_sleep_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        self.confirm_popup.lb_title.text = 'Machine Is Sleeping'
        self.confirm_popup.lb_content.text = 'Confirm to reset machine?'
        self.confirm_popup.confirm = partial(self.resetMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def resetMachine(self):
        self.controller.reset()
    # -----------------------------------------------------------------------
    def unlockMachine(self):
        self.controller.unlock()

    # -----------------------------------------------------------------------
    def open_rename_input_popup(self):
        self.input_popup.lb_title.text = 'Change name \'%s\' to:' % (self.file_popup.remote_rv.curr_selected_file)
        self.input_popup.txt_content.text = ''
        self.input_popup.confirm = partial(self.renameRemoteFile, self.file_popup.remote_rv.curr_selected_file)
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_newfolder_input_popup(self):
        self.input_popup.lb_title.text = 'Input new folder name:'
        self.input_popup.txt_content.text = ''
        self.input_popup.confirm = self.createRemoteDir
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_wifi_password_input_popup(self):
        self.input_popup.lb_title.text = 'Input WiFi password of %s:' % self.input_popup.cache_var1
        self.input_popup.txt_content.text = ''
        self.input_popup.confirm = self.connectToWiFi
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def check_and_upload(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        filename = os.path.basename(os.path.normpath(filepath))
        if len(list(filter(lambda person: person['filename'] == filename, self.file_popup.remote_rv.data))) > 0:
            # show message popup
            self.confirm_popup.lb_title.text = 'File Already Exists'
            self.confirm_popup.lb_content.text = 'Confirm to overwrite file: \'%s\'?' % (filename)
            self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath)
            self.confirm_popup.open(self)
        else:
            self.uploadLocalFile(filepath)

    # -----------------------------------------------------------------------
    def open_local_file(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        app = App.get_running_app()
        app.selected_local_filename = filepath

        self.progress_popup.progress_value = 0
        self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.progress_text = 'Openning local file\n%s' % filepath
        self.progress_popup.open()

        Clock.schedule_once(self.load_selected_gcode_file, 0)

    # -----------------------------------------------------------------------
    def load_selected_gcode_file(self, *args):
        app = App.get_running_app()
        self.load(app.selected_local_filename)

    # -----------------------------------------------------------------------
    def check_and_cache(self):
        remote_path = self.file_popup.remote_rv.curr_selected_file
        remote_size = self.file_popup.remote_rv.curr_selected_filesize
        remote_post_path = remote_path.replace('/sd/', '')
        local_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), remote_post_path)
        app = App.get_running_app()
        app.selected_local_filename = local_path
        app.selected_remote_filename = remote_path
        self.wpb_play.value = 0

        if os.path.exists(local_path):
            # compare file using md5sum
            self.compareFileMD5(remote_path, local_path)
        else:
            # cache file directly
            self.cacheRemoteFile(remote_path, remote_size)

    # -----------------------------------------------------------------------
    def compareFileMD5(self, remote_path, local_path):
        self.local_md5 = Utils.md5(local_path)
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MD5
        self.controller.readEOF = False
        self.controller.readERR = False
        self.long_load_time = time.time()
        self.progress_popup.progress_value = 0
        self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.progress_text = 'Comparing cached file\n%s' % remote_path
        self.progress_popup.open()

        self.controller.md5Command(os.path.normpath(remote_path))

    # -----------------------------------------------------------------------
    def finishCompareFileMD5(self, *args):
        md5 = ''
        while self.controller.load_buffer.qsize() > 0:
            md5 = self.controller.load_buffer.get_nowait()
        if md5 != self.local_md5:
            self.cacheRemoteFile(self.file_popup.remote_rv.curr_selected_file, self.file_popup.remote_rv.curr_selected_filesize)
        else:
            app = App.get_running_app()
            self.progress_popup.progress_value = 100
            self.progress_popup.progress_text = 'Open cached file \n%s' % app.selected_local_filename
            self.progress_popup.btn_cancel.disabled = True
            Clock.schedule_once(self.load_selected_gcode_file, 0)

    # -----------------------------------------------------------------------
    def startLoadWiFi(self, button):
        self.wifi_ap_drop_down.open(button)
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = 'WiFi: Searching for network...'
        else:
            self.wifi_ap_status_bar = WiFiButton(ssid='WiFi: Searching for network...', color=(180 / 255, 180 / 255, 180 / 255, 1))
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

        # load wifi AP
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()
        self.controller.loadWiFiCommand()

    # -----------------------------------------------------------------------
    def finishLoadWiFi(self, *args):
        ap_list = []
        has_connected = False
        while self.controller.load_buffer.qsize() > 0:
            ap_info = self.controller.load_buffer.get_nowait().split(',')
            if len(ap_info) > 3:
                if ap_info[3] == '1':
                    has_connected = True
                ap_list.append({'ssid': ap_info[0], 'connected': True if ap_info[3] == '1' else False,
                                'encrypted': True if ap_info[1] == '1' else False, 'strength': (int)(ap_info[2])})

        self.wifi_ap_drop_down.clear_widgets()
        self.wifi_ap_status_bar = None
        self.wifi_ap_status_bar = WiFiButton(ssid = 'WiFi: Connected' if has_connected else 'WiFi: Not Connected', color=(180 / 255, 180 / 255, 180 / 255, 1))
        self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)
        if has_connected:
            btn = WiFiButton(ssid = 'Close Connection')
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(''))
            self.wifi_ap_drop_down.add_widget(btn)
        # interval
        btn = WiFiButton(height=20)
        self.wifi_ap_drop_down.add_widget(btn)
        for ap in ap_list:
            btn = WiFiButton(connected = ap['connected'], ssid = ap['ssid'], encrypted = ap['encrypted'], strength = ap['strength'])
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(btn.ssid))
            self.wifi_ap_drop_down.add_widget(btn)

    # -----------------------------------------------------------------------
    def loadWiFiError(self, error_msg, *args):
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = 'WiFi: ' + error_msg
        else:
            self.wifi_ap_status_bar = WiFiButton(ssid='WiFi: ' + error_msg, color=(200 / 255, 200 / 255, 200 / 255, 1))
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

    # -----------------------------------------------------------------------
    def loadConnWiFiError(self, error_msg, *args):
        # start loading
        if error_msg == '':
            while self.controller.load_buffer.qsize() > 0:
                self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        else:
            self.message_popup.lb_content.text = error_msg
        self.message_popup.btn_ok.disabled = False

    def finishLoadConnWiFi(self, *args):
        while self.controller.load_buffer.qsize() > 0:
            self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        self.message_popup.btn_ok.disabled = False

    # -----------------------------------------------------------------------
    def startLoadConfig(self):
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_CONFIG
        self.controller.readEOF = False
        self.controller.readERR = False
        self.config_load_time = time.time()
        self.controller.loadConfigCommand()

    def finishLoadConfig(self, *args):
        self.setting_list.clear()
        while self.controller.load_buffer.qsize() > 0:
            line = self.controller.load_buffer.get_nowait()
            name, value = line.partition("=")[::2]
            self.setting_list[name.strip()] = value.strip()
        self.load_config()

    # -----------------------------------------------------------------------
    def loadRemoteDir(self, ls_dir):
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_DIR
        self.controller.loadEOF = False
        self.controller.loadERR = False
        self.short_load_time = time.time()
        self.controller.lsCommand(os.path.normpath(ls_dir))

    # -----------------------------------------------------------------------
    def cacheRemoteFile(self, remote_path, remote_size):
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_FILE
        self.controller.readEOF = False
        self.controller.readERR = False
        self.controller.loadCANCEL = False
        self.controller.loadCANCELSENT = False
        # clear load buffer
        while self.controller.load_buffer.qsize() > 0:
            self.controller.load_buffer.get_nowait()
        self.controller.load_buffer_size = 0
        self.controller.total_buffer_size = remote_size
        self.long_load_time = time.time()
        self.progress_popup.progress_value = 0
        self.progress_popup.progress_text = 'Caching\n%s' % remote_path
        self.progress_popup.cancel = partial(self.cancelCacheFile)
        self.progress_popup.btn_cancel.disabled = False
        self.progress_popup.open()

        self.controller.catCommand(os.path.normpath(remote_path))

    # -----------------------------------------------------------------------
    def cancelCacheFile(self):
        self.controller.loadCANCEL = True
        self.controller.loadCANCELSENT = False

    # -----------------------------------------------------------------------
    def removeRemoteFile(self, filename):
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_RM
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        self.controller.rmCommand(os.path.normpath(filename))

    # -----------------------------------------------------------------------
    def renameRemoteFile(self, filename):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MV
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        new_name = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        if filename == new_name:
            return False
        self.controller.mvCommand(os.path.normpath(filename), os.path.normpath(new_name))
        return True

    # -----------------------------------------------------------------------
    def createRemoteDir(self):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MKDIR
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        dirname = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        self.controller.mkdirCommand(os.path.normpath(dirname))
        return True

    # -----------------------------------------------------------------------
    def connectToWiFi(self):
        password = self.input_popup.txt_content.text.strip()
        if not password:
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_CONN_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()

        self.message_popup.lb_content.text = 'Connecting to %s...\n' % self.input_popup.cache_var1
        self.message_popup.btn_ok.disabled = True
        self.message_popup.open()

        self.controller.connectWiFiCommand(self.input_popup.cache_var1, password)
        return True
    # -----------------------------------------------------------------------
    def uploadLocalFile(self, filepath):
        # load local file to queue
        self.controller.load_buffer_size = 0
        # clear load_buffer
        while self.controller.load_buffer.qsize() > 0:
            self.controller.load_buffer.get_nowait()
        with open(filepath, 'rb') as fp:
            for line in fp:
                self.controller.load_buffer.put(line.decode('utf-8'))
                self.controller.load_buffer_size += len(line)
        self.controller.total_buffer_size = self.controller.load_buffer_size
        self.controller.loadNUM = 0
        self.controller.sendNUM = SEND_FILE
        self.controller.sendEOF = False
        self.controller.sendCANCEL = False
        self.controller.MD5 = Utils.md5(filepath)
        self.send_long_time = time.time()
        self.progress_popup.progress_text = 'Uploading\n%s' % filepath
        self.progress_popup.cancel = partial(self.cancelUploadFile)
        self.progress_popup.btn_cancel.disabled = False
        self.progress_popup.open()
        remotename = os.path.join(self.file_popup.remote_rv.curr_dir, os.path.basename(os.path.normpath(filepath)))
        self.controller.uploadCommand(os.path.normpath(remotename))

    # -----------------------------------------------------------------------
    def cancelUploadFile(self):
        self.controller.sendCANCEL = True

    # -----------------------------------------------------------------------
    def fillRemoteDir(self, *args):
        dirs = []
        files = []
        while self.controller.load_buffer.qsize() > 0:
            line = self.controller.load_buffer.get_nowait().strip('\r').strip('\n')
            if len(line) > 0 and line[0] != "<":
                if line.endswith('/'):
                    dirs.append(line[:-1])
                else:
                    file_info = line.split()
                    if len(file_info) == 2:
                        files.append((file_info[0], file_info[1]))

        self.file_popup.remote_rv.fill_dir(sorted(dirs), sorted(files, key=lambda x: x[0]))

    # -----------------------------------------------------------------------
    def writeLocalFile(self, *args):
        app = App.get_running_app()
        file = open(app.selected_local_filename, 'w')
        try:
            while self.controller.load_buffer.qsize() > 0:
                line = self.controller.load_buffer.get_nowait()
                file.write(line)
        except:
            print(sys.exc_info()[1])
        file.close()

        self.progress_popup.progress_value = 100
        self.controller.load_buffer_size = 0

        #
        self.progress_popup.progress_text = 'Open cached file \n%s' % app.selected_local_filename
        self.progress_popup.btn_cancel.disabled = True
        Clock.schedule_once(self.load_selected_gcode_file, 0)


    # -----------------------------------------------------------------------
    def finishCancelCacheFile(self, *args):
        while self.controller.load_buffer.qsize() > 0:
            self.controller.load_buffer.get_nowait()
        self.progress_popup.dismiss()

    # -----------------------------------------------------------------------
    def loadError(self, error_msg, *args):
        # close progress popups
        self.progress_popup.dismiss()
        # show message popup
        self.message_popup.lb_content.text = error_msg
        self.message_popup.open()

    # -----------------------------------------------------------------------
    def updateCachingProgress(self, *args):
        self.progress_popup.progress_value = self.controller.load_buffer_size * 100.0 \
                                             / (1 if self.file_popup.remote_rv.curr_selected_filesize == 0 else self.file_popup.remote_rv.curr_selected_filesize)

    # --------------------------------------------------------------`---------
    def updateUploadProgress(self, *args):
        self.progress_popup.progress_value = (self.controller.total_buffer_size - self.controller.load_buffer_size) * 100.0 \
                                             / (1 if self.controller.total_buffer_size == 0 else self.controller.total_buffer_size)

    # --------------------------------------------------------------`---------
    def finishUploadProgress(self, *args):
        self.progress_popup.dismiss()

    # -----------------------------------------------------------------------
    def updateStatus(self, *args):
        try:
            now = time.time()
            self.heartbeat_time = now
            app = App.get_running_app()
            if app.state != CNC.vars["state"]:
                app.state = CNC.vars["state"]
                CNC.vars["color"] = STATECOLOR[app.state]
                self.status_data_view.color = CNC.vars["color"]
                if app.state == 'Hold':
                    self.holding = 1
                else:
                    self.holding = 0
                # update status
                self.status_data_view.main_text = app.state
                if app.state == NOT_CONNECTED:
                    self.status_data_view.minr_text = 'disconnect'
                    self.status_drop_down.btn_connect_usb.disabled = False
                    self.status_drop_down.btn_connect_wifi.disabled = False
                    self.status_drop_down.btn_disconnect.disabled = True
                else:
                    self.status_data_view.minr_text = 'status'
                    self.status_drop_down.btn_connect_usb.disabled = True
                    self.status_drop_down.btn_connect_wifi.disabled = True
                    self.status_drop_down.btn_disconnect.disabled = False

                self.status_drop_down.btn_unlock.disabled = (app.state != "Alarm")

            # load config, only one time per connection
            if not self.config_loaded and app.state == "Idle":
                self.startLoadConfig()

            # check alarm and sleep status
            if app.state == 'Alarm' or app.state == 'Sleep':
                if not self.alarm_triggered:
                    self.alarm_triggered = True
                    if app.state == 'Alarm':
                        self.open_halt_confirm_popup()
                    else:
                        self.open_sleep_confirm_popup()
            else:
                if self.alarm_triggered and self.confirm_popup.showing:
                    self.confirm_popup.dismiss()
                self.alarm_triggered = False

            # update x data
            self.x_data_view.main_text = "{:.3f}".format(CNC.vars["wx"])
            self.x_data_view.minr_text = "{:.3f}".format(CNC.vars["mx"])
            # update y data
            self.y_data_view.main_text = "{:.3f}".format(CNC.vars["wy"])
            self.y_data_view.minr_text = "{:.3f}".format(CNC.vars["my"])
            # update z data
            self.z_data_view.main_text = "{:.3f}".format(CNC.vars["wz"])
            self.z_data_view.minr_text = "{:.3f}".format(CNC.vars["mz"])
            # update a data
            self.a_data_view.main_text = "{:.3f}".format(CNC.vars["wa"])
            self.a_data_view.minr_text = "{:.3f}".format(CNC.vars["ma"])
            #update feed data
            self.feed_data_view.main_text = "{:.0f}".format(CNC.vars["curfeed"])
            if self.status_index % 2 == 0:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["OvFeed"]) + " %"
            else:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["tarfeed"])

            elapsed = now - self.control_list['feedrate_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setFeedScale(self.control_list['feedrate_scale'][1])
                    self.control_list['feedrate_scale'][0] = now - 2
            elif elapsed > 3 and self.feed_drop_down.opened:
                self.feed_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvFeed"]) + "%"
                self.feed_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarfeed"])
                if self.feed_drop_down.scale_slider.value != CNC.vars["OvFeed"]:
                    self.feed_drop_down.scale_slider.set_flag = True
                    self.feed_drop_down.scale_slider.value = CNC.vars["OvFeed"]

            # update spindle data
            self.spindle_data_view.main_text = "{:.0f}".format(CNC.vars["curspindle"])
            if self.status_index % 3 == 0:
                self.spindle_data_view.minr_text = "{:.0f}".format(CNC.vars["tarspindle"])
            elif self.status_index % 3 == 1:
                self.spindle_data_view.minr_text = "{:.0f}".format(CNC.vars["OvSpindle"]) + " %"
            else:
                self.spindle_data_view.minr_text = "{:.1f}".format(CNC.vars["spindletemp"]) + " °C"
            elapsed = now - self.control_list['spindle_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleScale(self.control_list['spindle_scale'][1])
                    self.control_list['spindle_scale'][0] = now - 2
            elif elapsed > 3 and self.spindle_drop_down.opened:
                self.spindle_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvSpindle"]) + "%"
                self.spindle_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarspindle"])
                self.spindle_drop_down.status_temp.value = "{:.1f}".format(CNC.vars["spindletemp"]) + "°C"
                if self.spindle_drop_down.scale_slider.value != CNC.vars["OvSpindle"]:
                    self.spindle_drop_down.scale_slider.set_flag = True
                    self.spindle_drop_down.scale_slider.value = CNC.vars["OvSpindle"]


            # update tool data
            if CNC.vars["tool"] < 0:
                self.tool_data_view.main_text = "None"
                self.tool_data_view.minr_text = "N/A"
            else:
                self.tool_data_view.minr_text = "{:.3f}".format(CNC.vars["tlo"])
                if CNC.vars["tool"] == 0:
                    self.tool_data_view.main_text = "Probe"
                else:
                    self.tool_data_view.main_text = "{:.0f}".format(CNC.vars["tool"])

            # update laser data
            self.laser_data_view.active = CNC.vars["lasermode"]
            self.laser_data_view.main_text = "{:.1f}".format(CNC.vars["laserpower"])
            self.laser_data_view.minr_text = "{:.0f}".format(CNC.vars["laserscale"]) + " %"

            elapsed = now - self.control_list['laser_mode'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserMode(self.control_list['laser_mode'][1])
                    self.control_list['laser_mode'][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.switch.active != CNC.vars["lasermode"]:
                    self.laser_drop_down.switch.set_flag = True
                    self.laser_drop_down.switch.active = CNC.vars["lasermode"]

            elapsed = now - self.control_list['laser_test'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserTest(self.control_list['laser_test'][1])
                    self.control_list['laser_test'][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.test_switch.active != CNC.vars["lasertesting"]:
                    self.laser_drop_down.test_switch.set_flag = True
                    self.laser_drop_down.test_switch.active = CNC.vars["lasertesting"]

            elapsed = now - self.control_list['laser_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserScale(self.control_list['laser_scale'][1])
                    self.control_list['laser_scale'][0] = now - 2
            elif elapsed > 3 and self.laser_drop_down.opened:
                if self.laser_drop_down.scale_slider.value != CNC.vars["laserscale"]:
                    self.laser_drop_down.scale_slider.set_flag = True
                    self.laser_drop_down.scale_slider.value = CNC.vars["laserscale"]

            # update progress bar and set selected
            if CNC.vars["playedlines"] < 0:
                # not playing
                app.playing = False
                self.wpb_play.value = 0
                self.progress_info = ""
            else:
                app.playing = True
                # playing file remotely
                if self.played_lines != CNC.vars["playedlines"]:
                    self.played_lines = CNC.vars["playedlines"]
                    self.wpb_play.value = CNC.vars["playedpercent"]
                    self.progress_info = ''
                    if app.selected_remote_filename != '' and self.selected_file_line_count > 0:
                        # update gcode list
                        self.gcode_rv.set_selected(self.played_lines - 1)
                        # update gcode viewer
                        self.gcode_viewer.set_distance_by_lineidx(self.played_lines, 0.5)
                        # update progress info
                        self.progress_info = os.path.basename(app.selected_remote_filename) + ' ( {}/{} - {}%, {} elapsed'.format( \
                                                     self.played_lines, self.selected_file_line_count, int(self.wpb_play.value), Utils.second2hour(CNC.vars["playedseconds"]))
                        if self.wpb_play.value > 0:
                            self.progress_info = self.progress_info + ', {} to go )'.format(Utils.second2hour((100 - self.wpb_play.value) * CNC.vars["playedseconds"] / self.wpb_play.value))
                        else:
                            self.progress_info = self.progress_info + ' )'
        except:
            print(sys.exc_info()[1])

    # -----------------------------------------------------------------------
    def updateDiagnose(self, *args):
        try:
            now = time.time()

            # control spindle
            self.diagnose_popup.sw_spindle.disabled = CNC.vars['lasermode']
            self.diagnose_popup.sl_spindle.disabled = CNC.vars['lasermode']
            elapsed = now - self.control_list['spindle_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(self.control_list['spindle_switch'][1], self.diagnose_popup.sl_spindle.slider.value)
                    self.control_list['spindle_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_spindle.switch.active != CNC.vars["sw_spindle"]:
                    self.diagnose_popup.sw_spindle.set_flag = True
                    self.diagnose_popup.sw_spindle.switch.active = CNC.vars["sw_spindle"]
            elapsed = now - self.control_list['spindle_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(self.diagnose_popup.sw_spindle.switch.active, self.control_list['spindle_slider'][1])
                    self.control_list['spindle_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindle.slider.value != CNC.vars["sl_spindle"]:
                    self.diagnose_popup.sl_spindle.set_flag = True
                    self.diagnose_popup.sl_spindle.slider.value = CNC.vars["sl_spindle"]

            # control spindle fan
            elapsed = now - self.control_list['spindlefan_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindlefanSwitch(self.control_list['spindlefan_switch'][1], self.diagnose_popup.sl_spindlefan.slider.value)
                    self.control_list['spindlefan_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_spindlefan.switch.active != CNC.vars["sw_spindlefan"]:
                    self.diagnose_popup.sw_spindlefan.set_flag = True
                    self.diagnose_popup.sw_spindlefan.switch.active = CNC.vars["sw_spindlefan"]
            elapsed = now - self.control_list['spindlefan_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindlefanSwitch(self.diagnose_popup.sw_spindlefan.switch.active, self.control_list['spindlefan_slider'][1])
                    self.control_list['spindlefan_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindlefan.slider.value != CNC.vars["sl_spindlefan"]:
                    self.diagnose_popup.sl_spindlefan.set_flag = True
                    self.diagnose_popup.sl_spindlefan.slider.value = CNC.vars["sl_spindlefan"]

            # control vacuum
            elapsed = now - self.control_list['vacuum_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumSwitch(self.control_list['vacuum_switch'][1], self.diagnose_popup.sl_vacuum.slider.value)
                    self.control_list['vacuum_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_vacuum.switch.active != CNC.vars["sw_vacuum"]:
                    self.diagnose_popup.sw_vacuum.set_flag = True
                    self.diagnose_popup.sw_vacuum.switch.active = CNC.vars["sw_vacuum"]
            elapsed = now - self.control_list['vacuum_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumSwitch(self.diagnose_popup.sw_vacuum.switch.active, self.control_list['vacuum_slider'][1])
                    self.control_list['vacuum_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_vacuum.slider.value != CNC.vars["sl_vacuum"]:
                    self.diagnose_popup.sl_vacuum.set_flag = True
                    self.diagnose_popup.sl_vacuum.slider.value = CNC.vars["sl_vacuum"]

            # control laser
            self.diagnose_popup.sw_laser.disabled = not CNC.vars['lasermode']
            self.diagnose_popup.sl_laser.disabled = not CNC.vars['lasermode']
            elapsed = now - self.control_list['laser_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserSwitch(self.control_list['laser_switch'][1], self.diagnose_popup.sl_laser.slider.value)
                    self.control_list['laser_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_laser.switch.active != CNC.vars["sw_laser"]:
                    self.diagnose_popup.sw_laser.set_flag = True
                    self.diagnose_popup.sw_laser.switch.active = CNC.vars["sw_laser"]
            elapsed = now - self.control_list['laser_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserSwitch(self.diagnose_popup.sw_laser.switch.active, self.control_list['laser_slider'][1])
                    self.control_list['laser_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_laser.slider.value != CNC.vars["sl_laser"]:
                    self.diagnose_popup.sl_laser.set_flag = True
                    self.diagnose_popup.sl_laser.slider.value = CNC.vars["sl_laser"]

            # control light
            elapsed = now - self.control_list['light_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLightSwitch(self.control_list['light_switch'][1])
                    self.control_list['light_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_light.switch.active != CNC.vars["sw_light"]:
                    self.diagnose_popup.sw_light.set_flag = True
                    self.diagnose_popup.sw_light.switch.active = CNC.vars["sw_light"]

            # control tool sensor power
            elapsed = now - self.control_list['tool_sensor_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setToolSensorSwitch(self.control_list['tool_sensor_switch'][1])
                    self.control_list['tool_sensor_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_tool_sensor_pwr.switch.active != CNC.vars["sw_tool_sensor_pwr"]:
                    self.diagnose_popup.sw_tool_sensor_pwr.set_flag = True
                    self.diagnose_popup.sw_tool_sensor_pwr.switch.active = CNC.vars["sw_tool_sensor_pwr"]

            # update states
            self.diagnose_popup.st_x_min.state = CNC.vars["st_x_min"]
            self.diagnose_popup.st_x_max.state = CNC.vars["st_x_max"]
            self.diagnose_popup.st_y_min.state = CNC.vars["st_y_min"]
            self.diagnose_popup.st_y_max.state = CNC.vars["st_y_max"]
            self.diagnose_popup.st_z_max.state = CNC.vars["st_z_max"]
            self.diagnose_popup.st_cover.state = CNC.vars["st_cover"]
            self.diagnose_popup.st_probe.state = CNC.vars["st_probe"]
            self.diagnose_popup.st_calibrate.state = CNC.vars["st_calibrate"]
            self.diagnose_popup.st_atc_home.state = CNC.vars["st_atc_home"]
            self.diagnose_popup.st_tool_sensor.state = CNC.vars["st_tool_sensor"]
        except:
            print(sys.exc_info()[1])

    def update_control(self, name, value):
        if name in self.control_list:
            self.control_list[name][0] = time.time()
            self.control_list[name][1] = value

    def moveLineIndex(self, up = True):
        if up:
            self.test_line = self.test_line - 1
        else:
            self.test_line = self.test_line + 1
        if self.test_line == 0:
            self.test_line = 1
        self.gcode_rv.set_selected(self.test_line - 1)

    def execCallback(self, line):
        self.manual_rv.data.append({'text': line, 'color': (200/255, 200/255, 200/255, 1)})

    # -----------------------------------------------------------------------
    def openUSB(self, device):
        try:
            self.controller.open(CONN_USB, device)
        except:
            print(sys.exc_info()[1])
        self.updateStatus()
        self.status_drop_down.select('')

    # -----------------------------------------------------------------------
    def openWIFI(self, address):
        try:
            self.controller.open(CONN_WIFI, address)
        except:
            print(sys.exc_info()[1])
        self.updateStatus()
        self.status_drop_down.select('')

    # -----------------------------------------------------------------------
    def connWIFI(self, ssid):
        if ssid == '':
            self.controller.disconnectWiFiCommand()
        else:
            # open wifi conection popup window
            self.input_popup.cache_var1 = ssid
            self.open_wifi_password_input_popup()

    # -----------------------------------------------------------------------
    def close(self):
        try:
            self.controller.close()
        except:
            print(sys.exc_info()[1])
        self.updateStatus()

    # -----------------------------------------------------------------------
    def load_config(self):
        if self.config_loaded:
            return
        with open('config.json', 'r') as fd:
            data = json.loads(fd.read())
            basic_config = []
            advanced_config = []
            restore_config = []
            self.setting_type_list.clear()
            for setting in data:
                if 'type' in setting:
                    has_setting = False
                    if setting['type'] != 'title':
                        if 'key' in setting and 'section' in setting and setting['key'] in self.setting_list:
                            has_setting = True
                            self.config.setdefaults(setting['section'], {setting['key']: Utils.from_config(setting['type'], self.setting_list[setting['key']])})
                            self.setting_type_list[setting['key']] = setting['type']
                        else:
                            print('key: {} has no setting value'.format(setting['key']))
                    else:
                        has_setting = True
                    # construct json objects
                    if has_setting:
                        if 'section' in setting and setting['section'] == 'Basic':
                            basic_config.append(setting)
                        elif 'section' in setting and setting['section'] == 'Advanced':
                            advanced_config.append(setting)
                    elif 'section' in setting and setting['section'] == 'Restore':
                        self.config.setdefaults(setting['section'], {
                            setting['key']: Utils.from_config(setting['type'], '')})
                        restore_config.append(setting)
            # clear title section
            for basic in basic_config:
                if basic['type'] == 'title' and 'section' in basic:
                    basic.pop('section')
            for advanced in advanced_config:
                if advanced['type'] == 'title' and 'section' in advanced:
                    advanced.pop('section')

            self.config_popup.settings_panel.add_json_panel('Basic', self.config, data=json.dumps(basic_config))
            self.config_popup.settings_panel.add_json_panel('Advanced', self.config, data=json.dumps(advanced_config))
            self.config_popup.settings_panel.add_json_panel('Restore', self.config, data=json.dumps(restore_config))
            self.config_loaded = True

    # -----------------------------------------------------------------------
    def gcode_play_call_back(self, distance, line_number):
        self.gcode_play_slider.value = distance * 1000.0 / self.gcode_viewer_distance

    # -----------------------------------------------------------------------
    def gcode_play_to_start(self):
        self.gcode_viewer.set_pos_by_distance(0)
        self.gcode_viewer.enable_dynamic_displaying(False)

    # -----------------------------------------------------------------------
    def gcode_play_to_end(self):
        self.gcode_viewer.show_all()

    # -----------------------------------------------------------------------
    def gcode_play_speed_up(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 2)

    # -----------------------------------------------------------------------
    def gcode_play_speed_down(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 0.5)

    # -----------------------------------------------------------------------
    def gcode_play_toggle(self):
        if self.gcode_playing:
            self.gcode_playing = False
            self.gcode_viewer.dynamic_display = False
        else:
            self.gcode_playing = True
            self.gcode_viewer.dynamic_display = True

    # -----------------------------------------------------------------------
    def clear_selection(self):
        self.gcode_rv.data = []
        self.gcode_rv.data_length = 0
        self.gcode_viewer.clearDisplay()
        self.wpb_play.value = 0

    # -----------------------------------------------------------------------
    def load(self, filepath):
        print(self.size, self.pos)

        self.loading_file = True

        self.cmd_manager.transition.direction = 'right'
        self.cmd_manager.current = 'gcode_cmd_page'

        try:
            f = open(filepath, "r")
        except:
            print(sys.exc_info()[1])
            self.loading_file = False
            return

        self.cnc.init()
        self.gcode_rv.data = []
        line_no = 1
        for line in f:
            line_txt = line[:-1].replace("\x0d", "")
            self.cnc.parseLine(line_txt, line_no)
            self.gcode_rv.data.append({'text': str(line_no).ljust(12) + line_txt.strip()})
            line_no += 1
        f.close()

        self.selected_file_line_count = line_no - 1
        self.gcode_rv.data_length = self.selected_file_line_count

        parsed_lines = []
        for block in self.cnc.blocks:
            for i, path in enumerate(block[1]):
                parsed_lines.append('X: {} Y: {} Z: {} A: {} Color: {} Line: {} Tool: {}'.format(
                    path[0],
                    path[1],
                    path[2],
                    path[3],
                    'Red' if path[4] else 'Green',
                    path[5],
                    block[0]))

        self.gcode_viewer.set_display_offset(self.content.x, self.content.y)
        self.gcode_viewer.load(parsed_lines)
        self.gcode_viewer.set_move_speed(GCODE_VIEW_SPEED)
        self.gcode_viewer.show_all()
        self.gcode_viewer_distance = self.gcode_viewer.get_total_distance()
        #
        self.file_popup.dismiss()
        self.progress_popup.dismiss()

        self.loading_file = False

    # -----------------------------------------------------------------------
    def send_cmd(self):
        to_send = self.manual_cmd.text.strip()
        if to_send:
            self.manual_rv.scroll_y = 0
            self.controller.executeCommand(to_send)
        self.manual_cmd.text = ''
        Clock.schedule_once(self.refocus_cmd)

    # -----------------------------------------------------------------------
    def refocus_cmd(self, dt):
        self.manual_cmd.focus = True

    def stop_run(self):
        self.stop.set()
        self.controller.stop.set()


class MakeraApp(App):
    state = StringProperty(NOT_CONNECTED)
    playing = BooleanProperty(False)
    show_gcode_ctl_bar = BooleanProperty(False)
    selected_local_filename = StringProperty('')
    selected_remote_filename = StringProperty('')

    def on_stop(self):
        self.root.stop_run()

    def build(self):
        self.settings_cls = SettingsWithSidebar
        self.use_kivy_settings = True

        return Makera()


if __name__ == '__main__':
    MakeraApp().run()