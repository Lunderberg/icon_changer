#!/usr/bin/env python3

import array
import ctypes
import os
from typing import Optional, Union, Dict, Tuple

from PIL import Image

from ._raw import (
    lib,
    XDisplay,
    XWindow,
    XAtom,
    XScreen,
    GetWindowProperty,
    QueryTree,
    PropMode,
    XErrorHandler,
    find_int_typecode,
    GetClassHint,
    SetClassHint,
)


def set_error_handling(error_handler):
    lib.XSetErrorHandler(XErrorHandler(error_handler))


class Atom:
    def __init__(self, display, xatom: Union[XAtom, str]):
        self.display = display
        self._atom = xatom

    def __repr__(self):
        return f"Atom({self.display}, {self.name})"

    @property
    def name(self):
        return lib.XGetAtomName(self.display._display, self._atom).decode("utf-8")


class Display:
    def __init__(self, name: Optional[str] = None):
        if name:
            name = name.encode("utf-8")
        self._display = lib.XOpenDisplay(name)

    @property
    def name(self):
        return lib.XDisplayName(self._display).decode("utf-8")

    def __repr__(self):
        cls_name = type(self).__name__
        arg = repr(self.name)
        return f"{cls_name}({arg})"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __del__(self):
        self.close()

    def close(self):
        if not hasattr(self, "_display") or self._display is None:
            return

        lib.XCloseDisplay(self._display)

        self._display = None

    def get_window(self, xid: int):
        return Window(self, XWindow(xid))

    def screen(self, screen_number: Optional[int] = None):
        if screen_number is None:
            ptr = lib.XDefaultScreenOfDisplay(self._display)
        else:
            ptr = lib.XScreenOfDisplay(self._display, screen_number)
        return Screen(self, ptr.contents)

    def intern_atom(self, name: str, only_if_exists: bool = False):
        xatom = lib.XInternAtom(
            self._display, name.encode("utf-8"), int(only_if_exists)
        )
        return Atom(self, xatom)

    def flush(self):
        lib.XFlush(self._display)

    def sync(self, discard_events=False):
        lib.XSync(self._display, discard_events)

    def set_synchronize(self, sync=True):
        lib.XSynchronize(self._display, sync)


class Screen:
    def __init__(self, display: Display, xscreen: XScreen):
        # Can access the C++ XDisplay object through XScreen, but not
        # the python Display object.  Therefore, initialize with both
        # and check consistency.
        assert xscreen.display.value == display._display.value

        self.display = display
        self._screen = xscreen

    @property
    def root(self):
        return Window(self.display, self._screen.root)


class Window:
    def __init__(self, display: Display, xwindow: XWindow):
        self.display = display
        self._window = xwindow

    def __repr__(self):
        return f"Window({self.display}, {self._window})"

    def get_property(
        self, prop: Union[Atom, str], expected_return_type: Union[Atom, str]
    ) -> array.array:
        if isinstance(prop, str):
            prop_name = prop
            prop = self.display.intern_atom(prop)
        elif isinstance(prop, Atom):
            prop_name = prop.name

        if isinstance(expected_return_type, str):
            expected_return_type = self.display.intern_atom(expected_return_type)

        return GetWindowProperty(
            self.display._display, self._window, prop._atom, expected_return_type._atom
        )

    def set_property(
        self,
        prop: Union[Atom, str],
        storage_type: Union[Atom, str],
        value: Union[array.array, bytes],
    ):
        if isinstance(prop, str):
            prop = self.display.intern_atom(prop)

        if isinstance(storage_type, str):
            storage_type = self.display.intern_atom(storage_type)

        nelements = len(value)
        if isinstance(value, bytes):
            nbits = 8
            packed_bytes = value
        elif isinstance(value, array.array):
            nbits = 8 * value.itemsize
            if nbits == 32 and value.typecode.lower() != "l":
                packed_bytes = array.array("l", value).tobytes()
            else:
                packed_bytes = value.tobytes()

        lib.XChangeProperty(
            self.display._display,
            self._window,
            prop._atom,
            storage_type._atom,
            nbits,
            PropMode.Replace,
            packed_bytes,
            nelements,
        )

    def delete_property(
        self,
        prop: Union[Atom, str],
    ):
        if isinstance(prop, str):
            prop = self.display.intern_atom(prop)

        lib.XDeleteProperty(self.display._display, self._window, prop._atom)

    def get_text_property(self, prop: Union[Atom, str]) -> str:
        # TODO: Handle "COMPOUND_STRING" type as well.
        value = self.get_property(prop, "UTF8_STRING")
        if value is None:
            return None
        else:
            return value.tobytes().decode("utf-8")

    def set_text_property(self, prop: Union[Atom, str], value: str) -> None:
        # TODO: Handle non-UTF strings as well.
        self.set_property(prop, "UTF8_STRING", value.encode("utf-8"))

    @property
    def active_window(self):
        value = self.get_property("_NET_ACTIVE_WINDOW", "WINDOW")
        if value is None:
            return None
        else:
            xwindow = XWindow(value[0])
            return Window(self.display, xwindow)

    @property
    def name(self):
        # TODO: Fall back to WM_NAME (STRING) if _NET_WM_NAME is
        # undefined.
        return self.get_text_property("_NET_WM_NAME")

    @name.setter
    def name(self, name: str):
        # TODO: Also set WM_NAME (STRING), WM_ICON_NAME (STRING), and
        # _NET_WM_ICON_NAME (UTF8_STRING).
        self.set_text_property("_NET_WM_NAME", name)

    @property
    def icon(self) -> Dict[Tuple[int, int], Image.Image]:
        data = self.get_property("_NET_WM_ICON", "CARDINAL")
        if data is None:
            return {}

        output = {}

        while data:
            width = data[0]
            height = data[1]
            image_data = data[2 : 2 + width * height]

            size = (width, height)
            output[size] = Image.frombytes("RGBA", size, image_data.tobytes())

            data = data[2 + width * height :]

        return output

    @icon.setter
    def icon(self, value: Dict[Tuple[int, int], Image.Image]) -> None:
        nbits = 32
        typecode = find_int_typecode(nbits)

        data = []
        for size, im in value.items():
            assert im.mode == "RGBA"
            data.append(array.array(typecode, size))
            data.append(array.array(typecode, im.tobytes()))
        data = sum(data[1:], data[0])

        backup = {
            p: getattr(self, p)
            for p in ["pid", "class_hint", "gtk_application_id", "startup_id"]
        }
        # Can't delete PID, because muffin checks for validity.
        # Instead, pick a random unknown PID.
        # TODO: Make it actually random.
        self.pid = 2 ** 21
        del self.class_hint
        del self.gtk_application_id

        try:
            self.set_property("_NET_WM_ICON", "CARDINAL", data)
        finally:
            for prop, val in backup.items():
                if val is not None:
                    setattr(self, prop, val)

    @icon.deleter
    def icon(self):
        self.delete_property("_NET_WM_ICON")

    def query_tree(self):
        xroot, xparent, xchildren = QueryTree(self.display._display, self._window)
        root = Window(self.display, xroot)
        if xparent.value:
            parent = Window(self.display, xparent)
        else:
            parent = None

        children = [Window(self.display, xchild) for xchild in xchildren]

        return root, parent, children

    @property
    def root_window(self):
        return self.query_tree()[0]

    @property
    def parent(self):
        return self.query_tree()[1]

    @property
    def children(self):
        return self.query_tree()[2]

    @property
    def is_root_window(self):
        return self.root_window._window.value == self._window.value

    @property
    def pid(self):
        prop = self.get_property("_NET_WM_PID", "CARDINAL")
        if prop is None:
            return None
        else:
            return prop[0]

    @pid.setter
    def pid(self, value: int):
        arr = array.array(find_int_typecode(32), [value])
        prop = self.set_property("_NET_WM_PID", "CARDINAL", arr)

    @pid.deleter
    def pid(self):
        self.delete_property("_NET_WM_PID")

    @property
    def all_windows(self):
        assert self.is_root_window, "Can only be called on root window"
        prop = self.get_property("_NET_CLIENT_LIST", "WINDOW")
        return [Window(self.display, XWindow(wid)) for wid in prop]

    def show(self):
        lib.XMapWindow(self.display._display, self._window)

    def hide(self):
        lib.XUnmapWindow(self.display._display, self._window)

    @property
    def class_hint(self):
        """Class hint of the window

        Used by Cinnamon to map to a *.desktop file, to share the
        cached icon.  Looks for a *.desktop file with a StartupWMClass that ma

        1. *.desktop with StartupWMClass matching the instance

        2. *.desktop with StartupWMClass matching the class

        3. *.desktop with filename matching the instance

        4. *.desktop with filename matching the class (only if
        heuristics say it probably isn't a browser)

        """
        return GetClassHint(self.display._display, self._window)

    @class_hint.setter
    def class_hint(self, value: Tuple[str, str]):
        res_name, res_class = value
        SetClassHint(self.display._display, self._window, res_name, res_class)

    @class_hint.deleter
    def class_hint(self):
        self.delete_property("WM_CLASS")

    @property
    def gtk_application_id(self):
        """ID of a GTK application

        Used by Cinnamon to map to a *.desktop file, to share the
        cached icon.  Looks for `${_GTK_APPLICATION_ID}.desktop`.

        """
        return self.get_text_property("_GTK_APPLICATION_ID")

    @gtk_application_id.setter
    def gtk_application_id(self, value: str):
        return self.set_text_property("_GTK_APPLICATION_ID", value)

    @gtk_application_id.deleter
    def gtk_application_id(self):
        self.delete_property("_GTK_APPLICATION_ID")

    @property
    def startup_id(self):
        """ID of the startup notification.

        Used by Cinnamon to try to identify the app that opened a
        window, in order to map to a *.desktop file, to share the
        cached icon for the window.  Looks for `$(basename
        ${APPLICATION_ID}).desktop`, where APPLICATION_ID is specified
        in the startup notification.

        Ref: https://specifications.freedesktop.org/desktop-entry-spec/desktop-entry-spec-latest.html#key-startupnotify

        """
        return self.get_text_property("_NET_STARTUP_ID")

    @startup_id.setter
    def startup_id(self, value: str):
        return self.set_text_property("_NET_STARTUP_ID", value)

    @startup_id.deleter
    def startup_id(self):
        self.delete_property("_NET_STARTUP_ID")
