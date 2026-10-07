#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <telegram-ios-source-dir>" >&2
  exit 1
fi

SOURCE_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PATCH_FILE="$REPO_DIR/patches/0001-xtreegram-branding-and-server.patch"

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  echo "Source dir is not a git repository: $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "Patch file not found: $PATCH_FILE" >&2
  exit 1
fi

# --check first so a stale patch fails loudly instead of half-applying. The patch
# is written against the commit pinned in UPSTREAM_REF; when upstream moves, this
# is the step that tells us the patch needs a rebase.
if git -C "$SOURCE_DIR" apply --check "$PATCH_FILE" >/dev/null 2>&1; then
  git -C "$SOURCE_DIR" apply "$PATCH_FILE"
  echo "Patch applied: $PATCH_FILE"
else
  echo "Patch cannot be applied cleanly. Upstream may have changed." >&2
  git -C "$SOURCE_DIR" apply --check "$PATCH_FILE"
fi

# Source-level fixes that are plain string replacements rather than patches: the
# lines around them carry trailing whitespace, which makes context-based diffs
# fragile. Each script asserts it found exactly what it expects.
#
# The server RSA key is baked in by a separate workflow step instead, because the
# key lives in config/ and may be refreshed without touching any code.
python3 "$SCRIPT_DIR/apply_app_group_fallback.py" "$SOURCE_DIR"

# Not a sideload workaround: an unguarded NULL inserted into an NSDictionary
# literal in BuildConfig.m, which is an instant SIGABRT. Included here so a
# sideloaded build does not die before it can even reach the login screen.
python3 "$SCRIPT_DIR/apply_buildconfig_guard.py" "$SOURCE_DIR"

# ImageIO faults inside __PNGReadPlugin while decoding the loose PNG textures
# of the first-run intro, killing the app ~40 ms after launch. The textures are
# decorative, so skip loading them.
python3 "$SCRIPT_DIR/apply_intro_texture_guard.py" "$SOURCE_DIR"

# Same screen, next step: the OpenGL machinery itself (EAGLContext, GLKView,
# animation timer) is the only OpenGL ES user in the app and is where the second
# crash report lands. Leave it unloaded.
python3 "$SCRIPT_DIR/apply_intro_disable.py" "$SOURCE_DIR"

# Because of the two lines above the intro no longer draws anything, so make sure
# its "Start Messaging" button is not the only way past the first screen.
python3 "$SCRIPT_DIR/apply_splash_auto_advance.py" "$SOURCE_DIR"

# And the crash that survived both of those. The stack lands inside the 1x1
# UIGraphicsImageRenderer probe in Display/Source/GenerateImage.swift that
# detects the device's graphics-context parameters -- stock upstream code we
# never touched. Route it onto the legacy branch that already exists in the same
# function instead.
python3 "$SCRIPT_DIR/apply_graphics_probe_guard.py" "$SOURCE_DIR"

# The crash that only became visible once the app survived past 14 ms. With the
# graphics probe fixed the process now reaches authorization-screen construction
# and dies at 1.75 s inside CKContainer.default(), called from
# CloudData.swift. CloudKit traps with brk #1 when the process has no
# com.apple.developer.icloud-container-identifiers entitlement, which is the
# case both for this unsigned build and for a sideload signed with a free Apple
# ID -- so it has to go regardless of how the IPA gets signed.
python3 "$SCRIPT_DIR/apply_clouddata_guard.py" "$SOURCE_DIR"

# The crash that appeared only after a SUCCESSFUL login (#19): the account
# context becomes ready, TelegramPermissions.requiredPermissions() asks about
# .siri, and INPreferences.siriAuthorizationStatus() raises an ObjC exception
# because the process has no com.apple.developer.siri entitlement. Not a brk
# this time -- an uncaught exception, so SIGABRT. Siri is off for good.
python3 "$SCRIPT_DIR/apply_siri_guard.py" "$SOURCE_DIR"
