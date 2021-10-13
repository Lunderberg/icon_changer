import array
import ctypes
import ctypes.util
from typing import Tuple, Optional, List

from ctypes import (
    c_char_p,
    c_void_p,
    c_char,
    c_int,
    c_uint,
    c_ushort,
    c_long,
    c_ulong,
    c_uint64,
    c_byte,
    c_ubyte,
    POINTER,
)
from enum import Enum


libname = ctypes.util.find_library("X11")
lib = ctypes.CDLL(libname)


class X11InternalError(RuntimeError):
    pass


# Data types used by Xlib
xid = c_uint64


class XDisplay(c_void_p):
    pass


class XWindow(xid):
    def __repr__(self):
        return f"XWindow(0x{self.value:x})"


class XAtom(c_uint64):
    def __repr__(self):
        return f"XAtom({self.value})"


class XScreen(ctypes.Structure):
    _fields_ = [
        ("ext_data", c_void_p),
        ("display", XDisplay),
        ("root", XWindow),
        ("width", c_int),
        ("height", c_int),
    ]


class XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_int),
        ("display", XDisplay),
        ("serial", c_ulong),
        ("error_code", c_byte),
        ("request_code", c_byte),
        ("minor_code", c_byte),
    ]


class XClassHint(ctypes.Structure):
    _fields_ = [
        ("res_name", c_char_p),
        ("res_class", c_char_p),
    ]


XErrorHandler = ctypes.CFUNCTYPE(c_int, XDisplay, XErrorEvent)


@XErrorHandler
def default_error_handler(display, event):
    buffer_length = 256
    buf = bytes(buffer_length)
    lib.XGetErrorText(display, event.error_code, buf, buffer_length)
    text = buf.strip(b"\x00").decode("utf-8")
    raise X11InternalError(text)


# Dummy metaclass needed to have PropMode inherit both from Enum and
# c_int.
class PropMode_metaclass(type(c_int), type(Enum)):
    pass


class PropMode(c_int, Enum, metaclass=PropMode_metaclass):
    Replace = 0
    Prepend = 1
    Append = 2


# Helper functions in cases where ctypes wrangling is needed.
def GetWindowProperty(
    display: XDisplay, window: XWindow, prop: XAtom, expected_return_type: XAtom
) -> array.array:
    """Helper function wrapping lib.XGetWindowProperty

    Handles unpacking partial reads into a single array.
    """
    # Maximum length of a single read.  In 32-bit ints, even if the X
    # client is on a 64-bit machine.
    long_length = 65536
    delete = False

    # Location of the next chunk.
    long_offset = 0

    chunks = []

    expected_return_type = XAtom(0)

    while True:
        actual_type_return = XAtom()
        actual_format_return = c_int()
        nitems_return = c_ulong()
        bytes_after_return = c_ulong()
        prop_return = POINTER(c_ubyte)()

        lib.XGetWindowProperty(
            display,
            window,
            prop,
            long_offset,
            long_length,
            delete,
            expected_return_type,
            ctypes.byref(actual_type_return),
            ctypes.byref(actual_format_return),
            ctypes.byref(nitems_return),
            ctypes.byref(bytes_after_return),
            ctypes.byref(prop_return),
        )

        try:

            if actual_type_return.value == 0:
                return None
                raise KeyError(f"Property {prop} not set for {window}")

            element_bits = actual_format_return.value
            if element_bits == 8:
                prop_type = c_char
            elif element_bits == 16:
                prop_type = c_short
            elif element_bits == 32:
                # format==32 means an unsigned long, even on platforms
                # with 64-bit longs.  In those cases, the high bits are
                # padded with zeros.
                prop_type = c_long
            else:
                raise RuntimeError(f"Unexpected bit-size of property: {element_bits}")

            typecode = find_int_typecode(element_bits)

            prop_arr = ctypes.cast(
                prop_return, POINTER(prop_type * nitems_return.value)
            ).contents
            chunks.append(array.array(typecode, prop_arr[:]))

        finally:
            lib.XFree(prop_return)

        if bytes_after_return.value == 0:
            break
        else:
            long_offset += long_length

    return sum(chunks[1:], chunks[0])


def QueryTree(
    xdisplay: XDisplay, xwindow: XWindow
) -> Tuple[XWindow, Optional[XWindow], List[XWindow]]:
    """Helper function wrapping lib.XQueryTree

    Returns a tuple of (root,parent,children).
    """

    root_return = XWindow()
    parent_return = XWindow()
    children_return = POINTER(XWindow)()
    num_children_return = c_uint()

    success = lib.XQueryTree(
        xdisplay,
        xwindow,
        ctypes.byref(root_return),
        ctypes.byref(parent_return),
        ctypes.byref(children_return),
        ctypes.byref(num_children_return),
    )

    if not success:
        raise X11InternalError("Failing calling XQueryTree")

    try:
        return (
            root_return,
            parent_return,
            [
                children_return[i]
                for i in range(num_children_return.value)
                if children_return[i]
            ],
        )
    finally:
        lib.XFree(children_return)


def find_int_typecode(bits):
    """Find array.array typecode for the appropriate bitsize

    array.array is nice to avoid pulling in np.array as a dependency,
    but uses the native int types.  Therefore, when packing data to
    send to the server, we need to find the right type.
    """
    for typecode in ["b", "h", "i", "l"]:
        typecode_bits = 8 * array.array(typecode, []).itemsize
        if typecode_bits == bits:
            return typecode

    raise RuntimeError(
        f"Unable to find array.array typecode for {element_bits}-bit signed integers"
    )


def GetClassHint(display: XDisplay, window: XWindow):
    class_hint_return = XClassHint()

    success = lib.XGetClassHint(display, window, ctypes.byref(class_hint_return))
    if success:
        # From
        # https://tronche.com/gui/x/xlib/ICC/client-to-window-manager/XGetClassHint.html,
        # the res_name and res_class strings should be passed to XFree
        # when done.  I *think* this is handled by ctypes, but should
        # check with valgrind at some point.

        return (
            class_hint_return.res_name.decode("ascii"),
            class_hint_return.res_class.decode("ascii"),
        )

    else:
        return None


def SetClassHint(display: XDisplay, window: XWindow, res_name: str, res_class: str):
    class_hint = XClassHint()
    class_hint.res_name = res_name.encode("ascii")
    class_hint.res_class = res_class.encode("ascii")
    lib.XSetClassHint(display, window, ctypes.byref(class_hint))


# Type definitions for Xlib functions
def _def_signature(name, argtypes=None, restype=None, errcheck=None):
    func = getattr(lib, name)
    func.argtypes = argtypes
    func.restype = restype
    if errcheck is not None:
        func.errcheck = errcheck


_def_signature("XGetErrorText", [XDisplay, c_int, c_char_p, c_int], c_int)
_def_signature("XSetErrorHandler", [XErrorHandler], XErrorHandler)
_def_signature("XOpenDisplay", [c_char_p], XDisplay)
_def_signature("XCloseDisplay", [XDisplay], None)
_def_signature("XDisplayName", [XDisplay], c_char_p)
_def_signature("XDefaultScreenOfDisplay", [XDisplay], POINTER(XScreen))
_def_signature("XScreenOfDisplay", [XDisplay, c_int], POINTER(XScreen))
_def_signature("XInternAtom", [XDisplay, c_char_p, c_int], XAtom)
_def_signature("XGetAtomName", [XDisplay, XAtom], c_char_p)
_def_signature(
    "XGetWindowProperty",
    [
        XDisplay,  # Display
        XWindow,  # Window
        XAtom,  # Property
        c_long,  # Offset, in number of longs
        c_long,  # Length to read, in number of longs
        c_int,  # Bool, whether to delete property after reading
        XAtom,  # Request type
        POINTER(XAtom),  # Return type of property
        POINTER(c_int),  # Return type of format (number of bits)
        POINTER(c_ulong),  # Return number of items returned
        POINTER(c_ulong),  # Return number of bytes remaining
        POINTER(POINTER(c_ubyte)),  # The returned data
    ],
    c_int,
)
_def_signature(
    "XChangeProperty",
    [
        XDisplay,  # Display
        XWindow,  # Window
        XAtom,  # Property
        XAtom,  # Storage type
        c_int,  # Element format (number of bits)
        PropMode,  # Mode
        c_char_p,  # Start of array
        c_int,  # Number of elements
    ],
    c_int,
)
_def_signature(
    "XDeleteProperty",
    [XDisplay, XWindow, XAtom],
    c_int,
)

_def_signature("XMapWindow", [XDisplay, XWindow], c_int)
_def_signature("XUnmapWindow", [XDisplay, XWindow], c_int)

_def_signature("XGetClassHint", [XDisplay, XWindow, POINTER(XClassHint)], c_int)
_def_signature("XSetClassHint", [XDisplay, XWindow, POINTER(XClassHint)], c_int)

_def_signature("XFree", [c_void_p], c_int)

_def_signature("XSynchronize", [XDisplay, c_int], None)
_def_signature("XSync", [XDisplay, c_int], c_int)
_def_signature("XFlush", [XDisplay], c_int)

_def_signature(
    "XQueryTree",
    [
        XDisplay,
        XWindow,  # Query window
        POINTER(XWindow),  # Root window
        POINTER(XWindow),  # Return parent
        POINTER(POINTER(XWindow)),  # Return children
        POINTER(c_uint),  # Return num children
    ],
    c_int,
)

lib.XSetErrorHandler(default_error_handler)
