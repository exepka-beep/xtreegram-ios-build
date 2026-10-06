#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Never let the first-run intro become a dead end.

Why this is needed
------------------
`AuthorizationSequenceSplashController` is the very first screen a fresh install
shows, and it is the only place in the app that uses `RMIntroViewController`.
Leaving it requires the user to press the "Start Messaging" button that
`RMIntroViewController` creates and shows as part of its animation.

Because the intro's texture load has to be disabled (see
`apply_intro_texture_guard.py`), the intro no longer draws its sprites, so we
cannot rely on that button appearing at the moment the animation expects it. A
splash that cannot be dismissed would leave the app unusable even though nothing
is actually broken.

This adds a plain safety net: if the user has not started the login flow within
a few seconds, continue automatically. Tapping "Start Messaging" first still
works exactly as before -- the flag set at the top of `activateLocalization`
makes sure the flow can only start once.

Idempotent: re-running is a no-op.
"""

import io
import os
import sys

TARGET = os.path.join(
    "submodules", "AuthorizationUI", "Sources", "AuthorizationSequenceSplashController.swift"
)

PROP_ANCHOR = "    private let activateLocalizationDisposable = MetaDisposable()\n"

APPEAR_ANCHOR = "        controller.viewDidAppear(animated)\n    }\n"

ACTIVATE_ANCHOR = "    private func activateLocalization(_ code: String) {\n"

MARKER = "Xtreegram: the intro is decorative"

PROP_INSERT = (
    "\n"
    "    // Xtreegram: set once the login flow has been started, so the intro\n"
    "    // auto-advance below can never trigger a second time.\n"
    "    private var xtreegramDidActivateLocalization = false\n"
)

APPEAR_INSERT = (
    "        controller.viewDidAppear(animated)\n"
    "        \n"
    "        // Xtreegram: the intro is decorative, and its texture load is disabled\n"
    "        // on this build, so never let it become a dead end -- if the user has\n"
    "        // not pressed \"Start Messaging\" after a few seconds, continue anyway.\n"
    "        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in\n"
    "            guard let strongSelf = self, !strongSelf.xtreegramDidActivateLocalization else {\n"
    "                return\n"
    "            }\n"
    "            guard strongSelf.controller.view.superview != nil else {\n"
    "                return\n"
    "            }\n"
    "            strongSelf.activateLocalization(\"en\")\n"
    "        }\n"
    "    }\n"
)

ACTIVATE_INSERT = (
    "    private func activateLocalization(_ code: String) {\n"
    "        self.xtreegramDidActivateLocalization = true\n"
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
        print("usage: apply_splash_auto_advance.py <telegram-ios-source-dir>", file=sys.stderr)
        return 2

    src = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(src):
        print("target not found: %s" % src, file=sys.stderr)
        return 1

    text = read_text_raw(src)

    if MARKER in text:
        print("splash auto-advance: already applied, nothing to do")
        return 0

    for name, anchor in (
        ("activateLocalizationDisposable property", PROP_ANCHOR),
        ("viewDidAppear tail", APPEAR_ANCHOR),
        ("activateLocalization declaration", ACTIVATE_ANCHOR),
    ):
        count = text.count(anchor)
        if count != 1:
            print(
                "expected exactly 1 occurrence of the %s anchor, found %d -- "
                "upstream changed, refusing to patch" % (name, count),
                file=sys.stderr,
            )
            return 1

    text = text.replace(PROP_ANCHOR, PROP_ANCHOR + PROP_INSERT, 1)
    text = text.replace(APPEAR_ANCHOR, APPEAR_INSERT, 1)
    text = text.replace(ACTIVATE_ANCHOR, ACTIVATE_INSERT, 1)
    write_text_raw(src, text)

    print("splash auto-advance: applied")
    print("  %s" % TARGET)
    print("  splash now continues on its own after 3s if the button is not pressed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
