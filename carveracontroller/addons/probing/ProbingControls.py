from kivy.uix.gridlayout import GridLayout
from kivy.properties import StringProperty
from ...addons.tooltips.Tooltips import ToolTipButton

class ProbeSettingLabel(GridLayout):
    label_text = StringProperty("")
    hint_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class ProbeButton(ToolTipButton):
    def __init__(self, image='', halign='center', valign='middle', **kwargs):
        super().__init__(**kwargs)
        self.halign = halign
        self.valign = valign
    
    def on_size(self, *args):
        pass
        #at some point add code to respect halign and valign in img