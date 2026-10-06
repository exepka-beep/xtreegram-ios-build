"""Force the device-graphics-context probe onto upstream's legacy code path.

Build #13's crash log symbolicated (by hand -- the binary is stripped, see
below) to this exact code in `submodules/Display/Source/GenerateImage.swift`:

    public static let shared: DeviceGraphicsContextSettings = getSharedDevideGraphicsContextSettings()
    ...
    if #available(iOS 10.0, *) {
        let opaqueFormat = UIGraphicsImageRendererFormat()
        ...
        let opaqueRenderer = UIGraphicsImageRenderer(bounds: ..., format: opaqueFormat)
        let _ = opaqueRenderer.image(actions: { context in
            opaqueSettings = OpaqueSettings(context: context.cgContext)   <-- frame 0
        })

The crash stack matches frame for frame:

    f0  our closure            <- fault
    f1  -[UIGraphicsImageRenderer runDrawingActions:completionActions:format:error:]
    f2  -[UIGraphicsImageRenderer runDrawingActions:completionActions:error:]
    f3  -[UIGraphicsImageRenderer _UIImageWithActions:]
    f4  our code
    f5  our code
    f6  _dispatch_client_callout
    f7  _dispatch_once_callout        <- the `static let`
    ...
    f22 -[UIView(CALayerDelegate) layoutSublayersOfLayer:]

So the app dies the first time anything asks for an image, inside the 1x1
`UIGraphicsImageRenderer` probe that detects the device's row alignment, bits
per pixel and colour space. We never touched this file -- it is stock upstream.

The fix here is deliberately boring: the same function already contains a
working implementation for iOS 9 that does the identical job with
`UIGraphicsBeginImageContextWithOptions` instead of `UIGraphicsImageRenderer`.
Making the condition pick that branch removes the crashing call without
inventing any new logic of our own.

The first attempt at this raised the gate to `#available(iOS 99.0, *)`, which
looks harmless and is not: it makes the nested `#available(iOS 12.0, *)` inside
the branch redundant, and Swift treats that as an **error**
("unnecessary check for 'iOS'; enclosing scope ensures guard will always be
true"). Build #16 died on it. The current version keeps the original iOS 10 gate
and adds a runtime term the compiler cannot fold, which avoids the diagnostic
entirely -- see the comment in REPLACEMENT.

This is a hypothesis test, not a proven fix: if the graphics stack is broken
for this install in general, the legacy path will fault somewhere else and we
will see that immediately in the next crash log -- which is exactly why the
same build also re-enables dSYM generation, so that log can be symbolicated
into function names instead of raw offsets.
"""

import os
import sys

TARGET = os.path.join("submodules", "Display", "Source", "GenerateImage.swift")

MARKER = "Xtreegram: legacy graphics context probe"

ANCHOR = "    if #available(iOS 10.0, *) {\n        let opaqueFormat = UIGraphicsImageRendererFormat()\n"

REPLACEMENT = (
    "    // " + MARKER + ".\n"
    "    // The branch below builds a 1x1 image with UIGraphicsImageRenderer and reads\n"
    "    // CGContext properties from inside its drawing block. On the target device\n"
    "    // that drawing block is where the process dies, so we take the legacy branch\n"
    "    // instead: it does the same job with UIGraphicsBeginImageContextWithOptions.\n"
    "    //\n"
    "    // The condition is deliberately NOT an availability trick. Raising the gate to\n"
    "    // an impossible iOS version (the first attempt) makes the nested\n"
    "    // `#available(iOS 12.0, *)` further down redundant, and Swift reports that as\n"
    "    // an error, not a warning: \"unnecessary check for 'iOS'; enclosing scope\n"
    "    // ensures guard will always be true\". Keeping the original iOS 10 gate and\n"
    "    // adding a runtime term sidesteps the diagnostic entirely -- the compiler\n"
    "    // cannot fold an environment lookup, so nothing is provably dead. Default is\n"
    "    // the legacy path; setting XT_IMAGERENDERER=1 in the scheme restores the\n"
    "    // modern one for comparison.\n"
    "    let xtreegramUseImageRendererProbe = ProcessInfo.processInfo.environment[\"XT_IMAGERENDERER\"] != nil\n"
    "    if #available(iOS 10.0, *), xtreegramUseImageRendererProbe {\n"
    "        let opaqueFormat = UIGraphicsImageRendererFormat()\n"
)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_graphics_probe_guard.py <source_dir>")

    path = os.path.join(sys.argv[1], TARGET)
    if not os.path.isfile(path):
        # Build #15 died here with a bare FileNotFoundError because TARGET said
        # `Sources` where upstream has `Source`. Say what is wrong in one line,
        # and say how to check it, instead of dumping a traceback into the log.
        raise SystemExit(
            "graphics probe guard: file not found: %s\n"
            "  Upstream layout may have changed. Verify with:\n"
            "  https://api.github.com/repos/TelegramMessenger/Telegram-iOS/contents/%s?ref=%s"
            % (path, TARGET.replace(os.sep, "/"), os.environ.get("UPSTREAM_REF", "<pinned ref>")))
    with open(path, "rb") as f:
        raw = f.read()

    crlf = raw.count(b"\r\n")
    text = raw.decode("utf-8")

    if MARKER in text:
        print("graphics probe guard: already applied, nothing to do")
        return

    if text.count(ANCHOR) != 1:
        raise SystemExit(
            "graphics probe guard: anchor found %d times, expected exactly 1 -- "
            "upstream changed, fix the anchor" % text.count(ANCHOR))

    text = text.replace(ANCHOR, REPLACEMENT, 1)

    out = text.encode("utf-8")
    if crlf:
        out = out.replace(b"\n", b"\r\n")

    with open(path, "wb") as f:
        f.write(out)

    print("graphics probe guard: applied")
    print("  crlf preserved: %d" % crlf)
    print("  bytes: %d -> %d" % (len(raw), len(out)))


if __name__ == "__main__":
    main()
