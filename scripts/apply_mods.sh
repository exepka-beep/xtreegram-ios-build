#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <telegram-ios-source-dir>" >&2
  exit 1
fi

SOURCE_DIR="$1"
PATCH_FILE="$(cd "$(dirname "$0")/.." && pwd)/patches/0001-xtreegram-branding-and-server.patch"

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
