#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop the first-run intro from decoding its loose PNG textures.

Why this is needed
------------------
`setup_texture()` in `submodules/RMIntro/Sources/platform/ios/texture_helper.m`
loads each sprite with `[UIImage imageNamed:fileName]`, i.e. through UIKit's
path-based image loading, and the very first thing the app does after launch is
call it 23 times from `-[RMIntroViewController setupGL]`.

On the target device that path is fatal. The crash report reads:

    faultingThread: 1 (com.apple.main-thread)
    esr: 0x82000007  (Instruction Abort) Translation fault, level 3
    pc = far = 0x19B8F1A48          <- jumped into unmapped memory

    <deduplicated_symbol>                        (ImageIO)
    __PNGReadPlugin::InitializePluginData        (ImageIO)
    IIOReadPlugin::callInitialize(bool&)         (ImageIO)
    IIO_Reader::InitImageAtOffset(...)           (ImageIO)
    IIOImageSource::makeImagePlus(...)           (ImageIO)
    IIOImageSource::getPropertiesAtIndexInternal (ImageIO)
    CGImageSourceCopyPropertiesAtIndex           (ImageIO)
    UIImageGetOrientationAndScale                (UIKitCore)
    ImageSourceAtPath                            (UIKitCore)
    +[UIImage imageNamed:inBundle:variableValue:withConfiguration:]
    setup_texture                                (RMIntro)
    -[UIViewController loadViewIfRequired]
    -[UIViewController view]

39.9 ms after `procStartAbsTime`, every single launch. The PNG files themselves
are intact: all 23 are present in the bundle and their chunk layout and iDOT
offset tables are internally consistent, so the fault is inside the system
decoder, not in our resources.

The textures only feed the decorative intro animation, so the app should not die
over them. Skip the load and report the same value the function already returns
when an image is missing (-1), which is a path upstream exercises and tolerates.
The intro still runs, it just draws no sprites, and the "Start Messaging" button
is a plain UIKit view that is unaffected.

Idempotent: re-running is a no-op.
"""

import io
import os
import sys

TARGET = os.path.join("submodules", "RMIntro", "Sources", "platform", "ios", "texture_helper.m")

HEAD_ANCHOR = (
    "GLuint setup_texture(NSString *fileName, UIColor *color)\n"
    "{\n"
)

TAIL_ANCHOR = (
    "    free(spriteData);\n"
    "    return texName;\n"
    "}\n"
)

MARKER = "Xtreegram: skipping intro texture"

GUARD = (
    "    // Xtreegram: ImageIO faults while decoding the loose PNG textures below\n"
    "    // (instruction abort inside __PNGReadPlugin), which kills the app ~40 ms\n"
    "    // after launch, before it can ever reach the login screen. The textures\n"
    "    // only feed the decorative first-run intro, so skip loading them and\n"
    "    // report the same failure value the code below already uses when an image\n"
    "    // is missing. The intro still runs; it just draws no sprites.\n"
    "    (void)color;\n"
    "    NSLog(@\"Xtreegram: skipping intro texture %@\", fileName);\n"
    "    return -1;\n"
    "#if 0\n"
)

TAIL_REPLACEMENT = (
    "    free(spriteData);\n"
    "    return texName;\n"
    "#endif\n"
    "}\n"
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
        print("usage: apply_intro_texture_guard.py <telegram-ios-source-dir>", file=sys.stderr)
        return 2

    src = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(src):
        print("target not found: %s" % src, file=sys.stderr)
        return 1

    text = read_text_raw(src)

    if MARKER in text:
        print("intro texture guard: already applied, nothing to do")
        return 0

    head_count = text.count(HEAD_ANCHOR)
    tail_count = text.count(TAIL_ANCHOR)
    if head_count != 1 or tail_count != 1:
        print(
            "expected exactly 1 setup_texture head and 1 tail anchor, "
            "found head=%d tail=%d -- upstream changed, refusing to patch"
            % (head_count, tail_count),
            file=sys.stderr,
        )
        return 1

    text = text.replace(HEAD_ANCHOR, HEAD_ANCHOR + GUARD, 1)
    text = text.replace(TAIL_ANCHOR, TAIL_REPLACEMENT, 1)
    write_text_raw(src, text)

    print("intro texture guard: applied")
    print("  %s" % TARGET)
    print("  setup_texture now returns -1 without touching ImageIO")
    return 0


if __name__ == "__main__":
    sys.exit(main())
