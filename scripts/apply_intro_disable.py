#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Disable the OpenGL half of the first-run intro.

Why this is needed
------------------
`-[RMIntroViewController loadGL]` is what creates the intro's OpenGL machinery:

    _context = [[EAGLContext alloc] initWithAPI:kEAGLRenderingAPIOpenGLES2];
    _glkView = [[GLKView alloc] initWithFrame:... context:_context];
    ...
    [self setupGL];          // loads 23 PNG textures through ImageIO
    [self startTimer];       // drives the whole animation from a timer

Both crashes we have crash reports for happen inside exactly this screen, and
both end the same way: the main thread jumps into unmapped memory
(`esr 0x82000007`, Instruction Abort / Translation fault, `pc == far`).

  1. build #12 — `setup_texture` -> `[UIImage imageNamed:]` -> ImageIO
     `__PNGReadPlugin::InitializePluginData` -> jump to unmapped memory, 39.9 ms.
  2. build #13 — after the texture load was removed, the very next thing the
     intro does during its first layout (a `dispatch_once` that renders an image
     with `UIGraphicsImageRenderer`) jumps to unmapped memory, 14.4 ms.

That is a 2014-era OpenGL ES 2 / GLKView component running on iOS 26.5, and it
is the only OpenGL ES user in the entire app. The intro is decorative, so the
cheap, honest fix is to stop loading it.

`viewDidLoad` is deliberately left alone: it still builds the plain UIKit parts
(background, page control, "Start Messaging" button), so the screen keeps
showing something recognisable instead of a blank view. With `_glkView` left
nil, everything that touches it is a no-op under Objective-C nil messaging:
`glkView:drawInRect:` never fires, `createAnimationSnapshot` returns an empty
image view, and `[_glkView display]` does nothing.

Idempotent: re-running is a no-op.
"""

import io
import os
import sys

TARGET = os.path.join("submodules", "RMIntro", "Sources", "platform", "ios", "RMIntroViewController.m")

ANCHOR = "    if (/*[[UIApplication sharedApplication] applicationState] != UIApplicationStateBackground*/true && !_isOpenGLLoaded)\n"

MARKER = "Xtreegram: OpenGL intro disabled"

GUARD = (
    "    // Xtreegram: OpenGL intro disabled. This is the only OpenGL ES user in\n"
    "    // the app, and on the target device the main thread ends up jumping into\n"
    "    // unmapped memory while this screen sets itself up (see\n"
    "    // apply_intro_texture_guard.py for the first crash report). The intro is\n"
    "    // decorative: leave _glkView nil so no GL context, no textures and no\n"
    "    // animation timer are ever created. The UIKit part of the splash still\n"
    "    // builds, and the splash auto-advance moves past it on its own.\n"
    "    return;\n"
    "    \n"
)


def read_text_raw(path):
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text_raw(path, text):
    # newline="\n" keeps the file LF-only, matching upstream. The default would
    # translate to os.linesep and produce a whole-file diff on Windows.
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    if len(sys.argv) != 2:
        print("usage: apply_intro_disable.py <telegram-ios-source-dir>", file=sys.stderr)
        return 2

    src = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(src):
        print("target not found: %s" % src, file=sys.stderr)
        return 1

    text = read_text_raw(src)

    if MARKER in text:
        print("intro disable: already applied, nothing to do")
        return 0

    count = text.count(ANCHOR)
    if count != 1:
        print(
            "expected exactly 1 occurrence of the loadGL guard anchor, found %d -- "
            "upstream changed, refusing to patch" % count,
            file=sys.stderr,
        )
        return 1

    text = text.replace(ANCHOR, GUARD + ANCHOR, 1)
    write_text_raw(src, text)

    print("intro disable: applied")
    print("  %s" % TARGET)
    print("  loadGL returns before creating the EAGLContext / GLKView")
    return 0


if __name__ == "__main__":
    sys.exit(main())
