#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Guard a NULL SecAccessControlRef in BuildConfig.m.

Why this is needed
------------------
`+[BuildConfig addApplicationSecretKey:isCheckKey:]` builds a Secure Enclave key
from an `NSDictionary` literal that embeds the result of
`SecAccessControlCreateWithFlags(...)`:

    SecAccessControlRef access;
    if (isCheckKey) { access = SecAccessControlCreateWithFlags(..., kSecAccessControlPrivateKeyUsage, NULL); }
    else            { access = SecAccessControlCreateWithFlags(..., kSecAccessControlUserPresence | kSecAccessControlPrivateKeyUsage, NULL); }
    NSDictionary *attributes = @{
        ...
        (id)kSecPrivateKeyAttrs: @{
            ...
            (id)kSecAttrAccessControl: (__bridge id)access,   // <-- NULL when the call failed
            ...
        },
    };

That function returns NULL when the requested protection class is not available
(most commonly: the device has no passcode, or the flags are rejected). A NULL
inserted into a dictionary literal raises NSInvalidArgumentException, which is
an uncaught exception -> SIGABRT -> the app dies instantly. Upstream's own
LocalAuth.swift guards the very same call with `guard let`, so this is a genuine
oversight in BuildConfig.m, not an intentional contract.

The fix is a plain early return: every caller of addApplicationSecretKey: already
treats a nil result as "hardware encryption unavailable" and continues.

This patch is behaviour-preserving everywhere the current code works: it only
changes the path that currently crashes.

Idempotent: re-running is a no-op.
"""

import io
import os
import sys

TARGET = os.path.join("submodules", "BuildConfig", "Sources", "BuildConfig.m")

# Unique: the only `NSDictionary *attributes = @{` in the file, and the only
# place that builds a Secure Enclave key.
ANCHOR = (
    "    NSDictionary *attributes = @{\n"
    "        (id)kSecAttrKeyType: (id)kSecAttrKeyTypeECSECPrimeRandom,\n"
    "        (id)kSecAttrKeySizeInBits: @256,\n"
)

MARKER = "Xtreegram: SecAccessControlCreateWithFlags returns NULL"

GUARD = (
    "    // Xtreegram: SecAccessControlCreateWithFlags returns NULL when the\n"
    "    // requested protection class is unavailable (for example when the device\n"
    "    // has no passcode). Inserting that NULL into the dictionary literal below\n"
    "    // raises NSInvalidArgumentException and kills the app on the spot, so bail\n"
    "    // out instead: every caller already treats a nil result as \"hardware\n"
    "    // encryption unavailable\" and carries on.\n"
    "    if (access == NULL) {\n"
    "        return nil;\n"
    "    }\n"
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
        print("usage: apply_buildconfig_guard.py <telegram-ios-source-dir>", file=sys.stderr)
        return 2

    src = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(src):
        print("target not found: %s" % src, file=sys.stderr)
        return 1

    text = read_text_raw(src)

    if MARKER in text:
        print("buildconfig guard: already applied, nothing to do")
        return 0

    count = text.count(ANCHOR)
    if count != 1:
        print(
            "expected exactly 1 occurrence of the Secure Enclave dictionary anchor, "
            "found %d -- upstream changed, refusing to patch" % count,
            file=sys.stderr,
        )
        return 1

    text = text.replace(ANCHOR, GUARD + ANCHOR, 1)
    write_text_raw(src, text)

    print("buildconfig guard: applied")
    print("  %s" % TARGET)
    print("  inserted: if (access == NULL) { return nil; }")
    return 0


if __name__ == "__main__":
    sys.exit(main())
