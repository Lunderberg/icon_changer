#!/usr/bin/env python3

import argparse
import random

from libx11_wrapper import Display

from PIL import Image, ImageOps


def dummy_icon():
    order = [0, 1, 2]
    random.shuffle(order)

    output = {}

    sizes = [(16, 16), (32, 32), (64, 64)]
    for size in sizes:
        im = Image.new("RGBA", size)

        pixels = im.load()

        for i in range(im.size[0]):
            for j in range(im.size[1]):
                val = (255 * i // im.size[0], 255 * j // im.size[1], 0)
                pixels[i, j] = (val[order[0]], val[order[1]], val[order[2]], 255)
        output[size] = im

    return output


def invert_image(im):
    if im.mode == "RGBA":
        r, g, b, a = im.split()
        rgb = Image.merge("RGB", (r, g, b))
        inverted = ImageOps.invert(rgb)
        ir, ig, ib = inverted.split()
        return Image.merge("RGBA", (ir, ig, ib, a))

    elif im.mode == "RGB":
        return ImageOps.invert(rgb)

    else:
        raise ValueError(f"Unsupported mode: {im.mode}")


def weirdify_all(display):
    root = display.screen().root
    for window in root.all_windows:
        window.class_hint = ("asdf", "asdf")
        # window.gtk_application_id = "qwer"
        del window.gtk_application_id
        window.icon = dummy_icon()


def disconnect_from_group(window):
    """Removes a window from the CinnamonApp it is in.

    If we want a window to have an independent icon, we need to foil
    Cinnamon/Muffin's caching strategy in cinnamon-window-tracker.c,
    get_app_for_window().  Otherwise, the cached icon read from a
    *.desktop file will continue to be used, rather than the icon we
    set in _NET_WM_ICON.

    """
    # Remove the existing window_group hint, so it can't share an
    # icon with the window group.
    wm_hints = window.wm_hints
    if "window_group" in wm_hints:
        del wm_hints["window_group"]
        window.wm_hints = wm_hints

    # And make sure the window tracker can't look up windows that
    # share a PID, and share an icon with them.

    # TODO: Make sure this doesn't have accidental collisions with
    # other window groups.  Can't just set it to -1, because Muffin's
    # reload_net_wm_pid in window-props.c checks if the value is
    # positive.

    # TODO: Change this back when we're done, so that we don't confuse
    # the window manager.  Only WM_CLASS and GTK_APPLICATION_ID
    # trigger tracked_window_changed(), so we can change the PID back
    # once we're done.
    max_proc_id = int(open("/proc/sys/kernel/pid_max").read())
    max_legal_value = 2 ** 31 - 1
    window.pid = random.randint(max_proc_id + 1, max_legal_value)

    # Need to set these to an empty value, because deletions don't
    # remove the window tracker's stored value.
    window.startup_id = ""
    window.gtk_application_id = ""
    window.class_hint = ("", "")


def main(args):
    display = Display()
    # For testing purposes, should use display.flush() or display.sync() once I know what I'm doing
    display.set_synchronize()

    root = display.screen().root
    term = root.active_window

    disconnect_from_group(term)
    term.icon = dummy_icon()


def arg_main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdb",
        action="store_true",
        help="Start a pdb post mortem on uncaught exception",
    )

    args = parser.parse_args()

    try:
        main(args)
    except Exception:
        if args.pdb:
            import pdb, traceback

            traceback.print_exc()
            pdb.post_mortem()
        raise


if __name__ == "__main__":
    arg_main()
