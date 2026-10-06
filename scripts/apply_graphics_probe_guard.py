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
Raising the availability gate to an iOS version that will never exist makes the
compiler take that branch on every device, which removes the crashing call
without inventing any new logic of our own.

This is a hypothesis test, not a proven fix: if the graphics stack is broken
for this install in general, the legacy path will fault somewhere else and we
will see that immediately in the next crash log -- which is exactly why the
same build also re-enables dSYM generation, so that log can be symbolicated
into function names instead of raw offsets.
"""

import os
import sys

TARGET = os.path.join("submodules", "Display", "Sources", "GenerateImage.swift")

MARKER = "Xtreegram: legacy graphics context probe"

ANCHOR = "    if #available(iOS 10.0, *) {\n        let opaqueFormat = UIGraphicsImageRendererFormat()\n"

REPLACEMENT = (
    "    // " + MARKER + ".\n"
    "    // The iOS 10+ branch below builds a 1x1 image with UIGraphicsImageRenderer\n"
    "    // and reads CGContext properties from inside its drawing block. On the\n"
    "    // target device that drawing block is where the process dies, so take the\n"
    "    // legacy branch instead: it does the same job with\n"
    "    // UIGraphicsBeginImageContextWithOptions. 99.0 is a version that will never\n"
    "    // exist, which is the least invasive way to make the compiler pick `else`\n"
    "    // without deleting upstream code we might want back later.\n"
    "    if #available(iOS 99.0, *) {\n"
    "        let opaqueFormat = UIGraphicsImageRendererFormat()\n"
)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: apply_graphics_probe_guard.py <source_dir>")

    path = os.path.join(sys.argv[1], TARGET)
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
