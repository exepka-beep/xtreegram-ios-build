"""Disable Siri integration, which throws without the Siri entitlement.

Build #19's crash log (`Telegram-2026-10-07-115430.000.ips`) is an
`EXC_CRASH / SIGABRT`, not the `brk #1` of #17, and it symbolicates to:

    f10  Intents  -[INPreferences _THROW_EXCEPTION_FOR_PROCESS_MISSING_ENTITLEMENT_com_apple_developer_siri]
    f13  Intents  -[INPreferences assertThisProcessHasSiriEntitlement]
    f14  Intents  -[INPreferences _siriAuthorizationStatus]
    f15  Intents  +[INPreferences siriAuthorizationStatus]
    f16  TelegramUIFramework  +0x3f4f0  ->  AppDelegate.application(_:didFinishLaunchingWithOptions:) closure #37
    f17  TelegramUIFramework  +0x2a615f0 -> TelegramPermissions.requiredPermissions(...)
    f18  TelegramUIFramework  +0x2a6275c -> DeviceAccess.authorizationStatus(siriAuthorization:)

So the call chain is:

    TelegramPermissions.requiredPermissions(...)   // wants .contacts, .notifications,
                                                  // .cellularData and .siri
      -> DeviceAccess.authorizationStatus(siriAuthorization:)
        -> our `siriAuthorization` closure in AppDelegate.swift
          -> INPreferences.siriAuthorizationStatus()   <- THROWS

`+[INPreferences siriAuthorizationStatus]` does not quietly return
`.notDetermined` without the `com.apple.developer.siri` entitlement: it calls
`assertThisProcessHasSiriEntitlement`, which raises an ObjC exception. That
becomes an uncaught-exception abort -- nothing to catch, the process is gone.
A free Apple ID provisioning profile cannot grant `com.apple.developer.siri`,
so the app must never ask. (The `NSSiriUsageDescription` key in Info.plist is a
*privacy* string and is unrelated; both are required, and we can only ever have
the first.)

Why this only appeared *after* a successful login: `requiredPermissions` runs
when the account context becomes ready. Before that the app is still in the
authorization flow and never asks about Siri. That matches the report exactly --
phone, code and password all worked, then a black screen and an instant exit,
and now every launch dies the same way because the account is already there.

Three edits, all in AppDelegate.swift:

1. `siriAuthorization` no longer calls `INPreferences.siriAuthorizationStatus()`
   and reports `.denied`. This is the proven crash and the only edit that is
   strictly required.

2. `requestSiriAuthorization` no longer calls
   `INPreferences.requestSiriAuthorization` and completes with `false`. Not
   observed in this crash log -- it sits on the `DeviceAccess.authorizeAccess`
   path, which reporting `.denied` should now avoid -- but it is the same
   framework and the same entitlement, and it costs nothing to remove.

3. `INInteraction.deleteAll()` is dropped. It is reached from
   `resetIntentsIfNeeded` in the *same* post-login block that crashed, on the
   next line of execution, so it is the most likely next failure. Nothing is
   ever donated because Siri is off, so there is nothing to delete.

The printed string is deliberate, exactly as in the graphics and CloudData
patches: it is the one real literal this patch adds, so its presence in the
shipped binary is provable with `work/xcheck.py` rather than inferred.
"""

import os
import re
import sys

TARGET = os.path.join("submodules", "TelegramUI", "Sources", "AppDelegate.swift")

MARKER = "Xtreegram: Siri integration disabled"

# Structural anchors. The block between them contains a line with trailing
# whitespace, so slicing it out is safer than pasting its exact bytes here.
BLOCK_START = "}, requestSiriAuthorization: { completion in"
BLOCK_END = "}, getWindowHost: {"

BLOCK_REPLACEMENT = '''}, requestSiriAuthorization: { completion in
            // Xtreegram: Siri integration disabled -- see the note on
            // siriAuthorization below. Requesting Siri authorization goes
            // through the same entitlement-gated Intents code.
            completion(false)
        }, siriAuthorization: {
            // Xtreegram: Siri integration disabled.
            //
            // The Intents framework's siriAuthorizationStatus() does not return
            // .notDetermined when the process lacks the
            // com.apple.developer.siri entitlement: it calls
            // assertThisProcessHasSiriEntitlement and raises an ObjC exception,
            // which aborts the process (SIGABRT) with no chance to catch it.
            // Neither an unsigned build nor a sideload signed with a free Apple
            // ID can carry that entitlement.
            //
            // This closure is what killed the app right after a successful
            // login: once the account context becomes ready,
            // TelegramPermissions.requiredPermissions() collects the
            // permissions it reports -- .contacts, .notifications,
            // .cellularData and .siri -- and DeviceAccess.authorizationStatus()
            // resolves each one by calling back in here.
            //
            // Reporting .denied is the honest answer: without the entitlement
            // the user cannot grant it either, so the Siri integration simply
            // stays off. Nothing else depends on it.
            print("Xtreegram: Siri integration disabled -- no com.apple.developer.siri entitlement")
            return .denied
        }, getWindowHost: {'''

# Indentation-agnostic on purpose: a literal replace with the wrong number of
# leading spaces silently does nothing, and the build would then look exactly
# like "the fix did not help".
DELETE_RE = re.compile(r"^([ \t]*)INInteraction\.deleteAll\(\)[ \t]*\r?\n", re.M)

DELETE_REPLACEMENT = (
    r"\1// Xtreegram: Siri integration disabled, so no intents were ever\n"
    r"\1// donated and there is nothing to delete. This call belongs to the\n"
    r"\1// same entitlement-gated family as the rest of the Intents framework.\n"
)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_siri_guard.py <source_dir>")

    path = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(path):
        raise SystemExit(
            "siri guard: file not found: %s\n"
            "  Upstream layout may have changed. Verify with:\n"
            "  https://api.github.com/repos/TelegramMessenger/Telegram-iOS/contents/%s?ref=%s"
            % (path, TARGET.replace(os.sep, "/"), os.environ.get("UPSTREAM_REF", "<pinned ref>")))

    with open(path, "rb") as f:
        raw = f.read()

    crlf = raw.count(b"\r\n")
    text = raw.decode("utf-8")

    if MARKER in text:
        print("siri guard: already applied, nothing to do")
        return

    for anchor, count in ((BLOCK_START, text.count(BLOCK_START)),
                          (BLOCK_END, text.count(BLOCK_END))):
        if count != 1:
            raise SystemExit(
                "siri guard: anchor %r found %d times, expected exactly 1 -- "
                "upstream changed, fix the anchor" % (anchor, count))

    start = text.index(BLOCK_START)
    end = text.index(BLOCK_END, start) + len(BLOCK_END)
    original_block = text[start:end]

    for expected in ("INPreferences.requestSiriAuthorization",
                     "INPreferences.siriAuthorizationStatus()",
                     "buildConfig.isSiriEnabled"):
        if expected not in original_block:
            raise SystemExit(
                "siri guard: extracted the wrong region -- %r is not in it "
                "(got %d bytes)" % (expected, len(original_block)))

    # The whole point is that this file is the only place that asks Siri
    # anything. A second entry point would just move the crash, so say so now
    # rather than after another 70-minute build. Count the *calls*, not the
    # names: `siriAuthorization:` is the binding label and has no "Status".
    for symbol in ("INPreferences.siriAuthorizationStatus()",
                   "INPreferences.requestSiriAuthorization"):
        n = text.count(symbol)
        if n != 1:
            raise SystemExit(
                "siri guard: %s appears %d times in this file, expected 1 -- "
                "a second Siri entry point would need its own fix" % (symbol, n))

    text = text[:start] + BLOCK_REPLACEMENT + text[end:]

    found = DELETE_RE.findall(text)
    if len(found) != 1:
        raise SystemExit(
            "siri guard: found %d 'INInteraction.deleteAll()' calls, expected exactly 1"
            % len(found))
    text = DELETE_RE.sub(DELETE_REPLACEMENT, text)

    for gone in ("INPreferences", "INInteraction.deleteAll()"):
        if gone in text:
            raise SystemExit(
                "siri guard: %r survived the patch (comments in this patch are "
                "worded so that this check stays exact)" % gone)

    out = text.encode("utf-8")
    if crlf:
        out = out.replace(b"\n", b"\r\n")

    with open(path, "wb") as f:
        f.write(out)

    print("siri guard: applied")
    print("  crlf preserved: %d" % crlf)
    print("  bytes: %d -> %d" % (len(raw), len(out)))
    print("  INPreferences left in file: %d" % text.count("INPreferences"))
    print("  siriAuthorizationStatus left in file: %d" % text.count("siriAuthorizationStatus"))


if __name__ == "__main__":
    main()
