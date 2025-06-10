from pyobjus import autoclass, protocol
from pyobjus.dylib_manager import load_framework, load_dylib, INCLUDE
from pathlib import Path
import ctypes

# Present the document picker
ios_lib = ctypes.CDLL(None)  # Load the main iOS application binary

def pick_file():
    try:
        ios_lib.objc_getClass.restype = ctypes.c_void_p
        ios_lib.sel_registerName.restype = ctypes.c_void_p
        ios_lib.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        # Get the DocumentPickerHelper class and selector
        class_name = b"DocumentPickerHelper"
        method_name = b"showDocumentPicker"

        nsclass = ios_lib.objc_getClass(class_name)
        selector = ios_lib.sel_registerName(method_name)

        # Call Objective-C method to show the document picker
        ios_lib.objc_msgSend(nsclass, selector)
    except Exception as e:
        print(f"Error calling Objective-C: {e}")