#!/usr/bin/env bash
set -euo pipefail

# Shrinks the unsigned IPA: drops unused extensions, prunes locales, strips
# binaries. An unsigned build is signed later on the installer's device, so
# anything removed here can never be recovered — keep the defaults conservative.

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <ipa-work-dir>" >&2
  exit 1
fi

WORK_DIR="$1"
PAYLOAD_DIR="$WORK_DIR/Payload"

if [[ ! -d "$PAYLOAD_DIR" ]]; then
  echo "Payload directory not found: $PAYLOAD_DIR" >&2
  exit 1
fi

shopt -s nullglob
app_dirs=("$PAYLOAD_DIR"/*.app)
if [[ ${#app_dirs[@]} -ne 1 ]]; then
  echo "Expected exactly one .app in Payload, found: ${#app_dirs[@]}" >&2
  exit 1
fi

APP_DIR="${app_dirs[0]}"
KEEP_LOCALES_RAW="${IPA_KEEP_LOCALES:-Base,en,ru}"
DROP_PLUGINS_RAW="${IPA_DROP_PLUGINS:-Watch,Widget,BroadcastUpload,Share}"

# Normalize CSV values by dropping spaces around items.
KEEP_LOCALES_CSV="$(printf '%s' "$KEEP_LOCALES_RAW" | tr -d '[:space:]')"
DROP_PLUGINS_CSV="$(printf '%s' "$DROP_PLUGINS_RAW" | tr -d '[:space:]')"

if [[ -z "$KEEP_LOCALES_CSV" ]]; then
  KEEP_LOCALES_CSV="Base"
fi

if [[ -z "$DROP_PLUGINS_CSV" ]]; then
  DROP_PLUGINS_CSV="Watch,Widget,BroadcastUpload,Share"
fi

payload_size_before_kb="$(du -sk "$PAYLOAD_DIR" | awk '{print $1}')"
echo "Slim IPA start: payload size ${payload_size_before_kb} KB"
echo "Keep locales: $KEEP_LOCALES_CSV"
echo "Drop plugin keywords: $DROP_PLUGINS_CSV"

IFS=',' read -r -a drop_keywords <<< "$DROP_PLUGINS_CSV"
plugins_dir="$APP_DIR/PlugIns"
if [[ -d "$plugins_dir" ]]; then
  for appex in "$plugins_dir"/*.appex; do
    [[ -e "$appex" ]] || continue
    appex_name="$(basename "$appex")"
    appex_name_lower="$(printf '%s' "$appex_name" | tr '[:upper:]' '[:lower:]')"
    remove_appex=0
    for keyword in "${drop_keywords[@]}"; do
      keyword_lower="$(printf '%s' "$keyword" | tr '[:upper:]' '[:lower:]')"
      if [[ -n "$keyword_lower" && "$appex_name_lower" == *"$keyword_lower"* ]]; then
        remove_appex=1
        break
      fi
    done
    if [[ "$remove_appex" -eq 1 ]]; then
      echo "Removing extension: $appex_name"
      rm -rf "$appex"
    fi
  done
fi

while IFS= read -r -d '' lproj_dir; do
  locale_name="$(basename "$lproj_dir")"
  locale_key="${locale_name%.lproj}"
  case ",$KEEP_LOCALES_CSV," in
    *",$locale_key,"*)
      ;;
    *)
      rm -rf "$lproj_dir"
      ;;
  esac
done < <(find "$APP_DIR" -type d -name "*.lproj" -print0)

# Xtreegram: `xcrun strip -x` used to run over every Mach-O here, swallowing its
# exit status with `|| true`. That was the only step in the whole pipeline that
# rewrites code binaries after the build produced and signed them, and the crash
# we are chasing is "the main thread jumps into unmapped memory" inside the
# app's own frameworks — which is the classic symptom of a binary whose
# signature no longer covers its contents. The binaries are now left exactly as
# the build produced them. The count is still reported so the log keeps telling
# us how many Mach-O files the bundle contains.
macho_count=0
while IFS= read -r -d '' file_path; do
  if LC_ALL=C file -b "$file_path" | grep -q "Mach-O"; then
    macho_count=$((macho_count + 1))
  fi
done < <(find "$APP_DIR" -type f -print0)
echo "Mach-O files left untouched (strip disabled): $macho_count"

find "$APP_DIR" -type d -name "SC_Info" -prune -exec rm -rf {} +
find "$APP_DIR" -type f -name ".DS_Store" -delete

payload_size_after_kb="$(du -sk "$PAYLOAD_DIR" | awk '{print $1}')"
delta_kb=$((payload_size_before_kb - payload_size_after_kb))
echo "Slim IPA done: payload size ${payload_size_after_kb} KB (saved ${delta_kb} KB)"
