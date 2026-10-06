#!/usr/bin/env python3
"""Let Xtreegram run without an App Group container.

Telegram-iOS keeps its data in the shared App Group container
``group.<bundle id>``. Reading it requires the
``com.apple.security.application-groups`` entitlement, which a free Apple ID
provisioning profile cannot grant, so on a sideloaded build
``FileManager.containerURL(forSecurityApplicationGroupIdentifier:)`` returns nil.

``AppDelegate`` then hits:

    guard let appGroupUrl = maybeAppGroupUrl else {
        self.mainWindow?.presentNative(UIAlertController(... "Error 2" ...))
        return true
    }

At that point there is no root view controller yet, so the alert is never
presented and ``didFinishLaunchingWithOptions`` returns having built nothing —
the window stays empty and the user sees a permanently black launch screen.

This script makes the lookup fall back to the app's own Documents directory, so
the app runs with a private container instead. Nothing is shared with the
extensions any more, which is fine: Xtreegram ships without extensions.

Usage: apply_app_group_fallback.py <telegram-ios-source-dir>
"""

import pathlib
import sys

TARGET = "submodules/TelegramUI/Sources/AppDelegate.swift"

OLD = (
    '        let maybeAppGroupUrl = FileManager.default.containerURL'
    '(forSecurityApplicationGroupIdentifier: appGroupName)\n'
)

NEW = (
    "        // Xtreegram: a free Apple ID provisioning profile cannot grant the\n"
    '        // "com.apple.security.application-groups" entitlement, so the shared\n'
    "        // container is nil on sideloaded builds. The guard further down then\n"
    '        // bails out with an "Error 2" alert that cannot be presented yet (no\n'
    "        // root view controller exists at that point), which leaves the app on\n"
    "        // a permanently black launch screen. Fall back to the app's own\n"
    "        // Documents directory instead of relying on the shared container.\n"
    "        //\n"
    "        // The explicit URL? annotation is required: the guard below still\n"
    "        // binds this with `guard let`, which only compiles when the value is\n"
    "        // Optional. `??` alone would narrow it to URL and break the build.\n"
    "        let maybeAppGroupUrl: URL? = FileManager.default.containerURL"
    "(forSecurityApplicationGroupIdentifier: appGroupName)"
    " ?? URL(fileURLWithPath: NSSearchPathForDirectoriesInDomains"
    "(.documentDirectory, .userDomainMask, true)[0])\n"
)

MARKER = "Xtreegram: a free Apple ID provisioning profile cannot grant the"


def read_text_raw(path):
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return handle.read()


def write_text_raw(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    target = pathlib.Path(sys.argv[1]) / TARGET
    if not target.is_file():
        raise SystemExit("not found: %s" % target)

    text = read_text_raw(target)
    if MARKER in text:
        print("app group fallback already applied to %s" % TARGET)
        return

    occurrences = text.count(OLD)
    if occurrences != 1:
        raise SystemExit(
            "expected exactly 1 app group lookup in %s, found %d — upstream changed, "
            "rebase this fix" % (TARGET, occurrences)
        )

    write_text_raw(target, text.replace(OLD, NEW))
    print("applied app group fallback to %s" % TARGET)
    # Echo the result so a CI log shows exactly what the compiler will see.
    for line in read_text_raw(target).split("\n"):
        if "maybeAppGroupUrl" in line and "containerURL" in line:
            print("  %s" % line.strip())


if __name__ == "__main__":
    main()
