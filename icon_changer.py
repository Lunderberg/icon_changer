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


def main(args):
    display = Display()
    # For testing purposes, should use display.flush() or display.sync() once I know what I'm doing
    display.set_synchronize()

    root = display.screen().root
    term = root.active_window
    # window = next(
    #     win for win in root.all_windows if win.name == "example GUI using pyqt5"
    # )
    # print(window)
    # print(window.name)

    # icon = window.icon
    # print(icon)
    # inverted = {size: invert_image(image) for size, image in icon.items()}
    # window.icon = inverted

    # print("PID = ", window.pid)

    # TODO: Maybe I need to get the window to be part of its own
    # CinnamonApp?  Looks like I'd need to set _GTK_APPLICATION_ID and
    # WM_CLASS to be something unique.  Though, that wouldn't explain
    # why Discord's icon doesn't change.

    # window.icon = dummy_icon()

    # print(window.class_hint)

    # If I change both WM_CLASS and _GTK_APPLICATION_ID to something
    # that doesn't have a .desktop file, then I can get the icon to
    # change.  It breaks if there's more than one window for a
    # program, but it's really close now.

    # term.class_hint = ("asdf", "asdf")
    # window.gtk_application_id = "qwer"
    del term.gtk_application_id
    term.pid = 5 * term.pid % (2 ** 22)
    term.icon = dummy_icon()

    # import IPython

    # IPython.embed()


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
