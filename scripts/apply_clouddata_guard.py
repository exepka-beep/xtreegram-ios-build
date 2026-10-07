"""Disable the CloudKit emergency-datacenter lookup.

Build #17's crash log (`faultingThread: 12`) symbolicated to:

    f0   CloudKit              +0xb4c0      <- brk #1, esr 0xF2000001
    f5   libdispatch.dylib     _dispatch_once_callout
    f7   TelegramCoreFramework CloudData.fetchRaw...(prefix:) +52
    f19  TelegramCoreFramework CloudData.CloudDataContextImpl.get(phoneNumber:) +652

and `submodules/CloudData/Sources/CloudData.swift` is where that lands:

    private func fetchRawData(prefix: String) -> Signal<Data, FetchError> {
        return Signal { subscriber in
            let container = CKContainer.default()          <- frame 7
            let publicDatabase = container.database(with: .public)
            publicDatabase.fetch(withRecordID: recordId, ...)
        }
    }

`CKContainer.default()` traps with `brk #1` (EXC_BREAKPOINT / SIGTRAP) when the
process has no `com.apple.developer.icloud-container-identifiers` entitlement.
That is exactly our situation: the unsigned IPA carries no entitlements at all
(no `_CodeSignature`, no `embedded.mobileprovision` -- verified), and a sideload
signed with a free Apple ID is granted only `application-identifier` and
`keychain-access-groups`. iCloud is not in a free provisioning profile, so this
trap fires after signing too. It happens inside a `dispatch_once` in CloudKit,
before any `NSError` can be produced, so there is nothing to catch -- the
process is gone.

What the lookup is for: the built-in datacenter list can be blocked by a
network, and Telegram then fetches a backup datacenter address from a *public*
CloudKit database, keyed by the first digit of the phone number. This build
talks to one hardcoded server, so the fallback buys us nothing.

Two edits, both minimal:

1. `fetchRawData` no longer touches CloudKit; it reports an immediate error.
   That is a path the callers already handle -- `fetch()` maps it to `nil` and
   the authorization flow simply proceeds without backup datacenter data.

2. `|> restart` is dropped from `fetch()`. This one matters: with an instantly
   failing signal, `restart` would re-subscribe the moment the error arrives and
   spin without ever yielding, because the only thing that stops the chain is
   `take(1)` seeing a *value*. Removing the retry makes it one attempt, one
   result -- and the retry was pointless anyway once CloudKit is out of the
   picture.

The printed string is deliberate: like XT_IMAGERENDERER in the graphics patch,
it is the one real literal this patch adds, so its presence in the shipped
binary is provable with `work/xcheck.py` instead of being inferred.
"""

import os
import re
import sys

TARGET = os.path.join("submodules", "CloudData", "Sources", "CloudData.swift")

MARKER = "Xtreegram: CloudKit backup datacenter lookup disabled"

FUNC_SIGNATURE = "private func fetchRawData(prefix: String) -> Signal<Data, FetchError> {"

REPLACEMENT_FUNC = '''private func fetchRawData(prefix: String) -> Signal<Data, FetchError> {
    return Signal { subscriber in
        // Xtreegram: CloudKit emergency-datacenter lookup disabled.
        //
        // CKContainer.default() traps with brk #1 (EXC_BREAKPOINT / SIGTRAP)
        // when the process has no com.apple.developer.icloud-container-identifiers
        // entitlement, and the trap fires inside a dispatch_once in CloudKit --
        // before any NSError can be returned, so it cannot be caught. Neither an
        // unsigned build nor a sideload signed with a free Apple ID has that
        // entitlement.
        //
        // The lookup is only a fallback for when the built-in datacenter list is
        // blocked, and this build talks to a single hardcoded server, so
        // skipping it costs nothing. An immediate error is a path the callers
        // already handle: fetch() maps it to nil and authorization proceeds
        // without backup datacenter data.
        print("Xtreegram: CloudKit backup datacenter lookup disabled for prefix", prefix)
        subscriber.putError(.generic)
        return ActionDisposable {
        }
    }
}
'''

# Indentation-agnostic on purpose: a literal-string replace with the wrong
# number of leading spaces silently does nothing, and the build then looks
# exactly like "the fix did not help" -- which would send us after the wrong
# cause. Count first, fail loudly.
RESTART_RE = re.compile(r"^[ \t]*\|> restart[ \t]*\r?\n", re.M)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_clouddata_guard.py <source_dir>")

    path = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(path):
        raise SystemExit(
            "clouddata guard: file not found: %s\n"
            "  Upstream layout may have changed. Verify with:\n"
            "  https://api.github.com/repos/TelegramMessenger/Telegram-iOS/contents/%s?ref=%s"
            % (path, TARGET.replace(os.sep, "/"), os.environ.get("UPSTREAM_REF", "<pinned ref>")))

    with open(path, "rb") as f:
        raw = f.read()

    crlf = raw.count(b"\r\n")
    text = raw.decode("utf-8")

    if MARKER in text:
        print("clouddata guard: already applied, nothing to do")
        return

    if text.count(FUNC_SIGNATURE) != 1:
        raise SystemExit(
            "clouddata guard: function signature found %d times, expected exactly 1 -- "
            "upstream changed, fix the anchor" % text.count(FUNC_SIGNATURE))

    # Slice the function out structurally instead of pasting its whole body into
    # this script. The body contains a line of trailing whitespace, which would
    # have to be reproduced byte for byte -- and the first occurrence of a line
    # that is exactly "}" is the function's own closing brace, because every
    # brace inside it is indented.
    start = text.index(FUNC_SIGNATURE)
    end_marker = "\n}\n"
    end = text.index(end_marker, start) + len(end_marker)
    original_func = text[start:end]

    for expected in ("CKContainer", "ActionDisposable", "putError"):
        if expected not in original_func:
            raise SystemExit(
                "clouddata guard: extracted the wrong region -- %r is not in it "
                "(got %d bytes)" % (expected, len(original_func)))

    # The whole point is that this is the only CloudKit entry point in the app.
    # If a second one ever appears, patching this function alone would just move
    # the crash, so say so now rather than after another 70-minute build.
    if text.count("CKContainer") != 1:
        raise SystemExit(
            "clouddata guard: CKContainer appears %d times in this file, expected 1 -- "
            "a second CloudKit entry point would need its own fix" % text.count("CKContainer"))

    text = text[:start] + REPLACEMENT_FUNC.rstrip("\n") + text[end - 1:]

    found = RESTART_RE.findall(text)
    if len(found) != 1:
        raise SystemExit(
            "clouddata guard: found %d '|> restart' lines in fetch(), expected exactly 1 -- "
            "without removing it the stubbed fetch would spin" % len(found))
    text = RESTART_RE.sub("", text)

    if "|> restart" in text:
        raise SystemExit("clouddata guard: a '|> restart' mention survived the removal")

    out = text.encode("utf-8")
    if crlf:
        out = out.replace(b"\n", b"\r\n")

    with open(path, "wb") as f:
        f.write(out)

    print("clouddata guard: applied")
    print("  crlf preserved: %d" % crlf)
    print("  bytes: %d -> %d" % (len(raw), len(out)))
    print("  CKContainer left in file: %d" % text.count("CKContainer"))


if __name__ == "__main__":
    main()
