#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Geely R621 · DiPlay wireless CarPlay — one-click installer
#
#   ./install.sh                      dry-run (prints every step, changes nothing)
#   ./install.sh --apply              backup -> build -> patch -> deploy -> reboot
#   ./install.sh --backup-only        take a full backup and stop
#   ./install.sh --apply --skip-reboot
#
# Safety model (same as tools/deploy_hal.py):
#   * dry-run by default, --apply is required to write anything
#   * every pre-existing file is copied to $BACKUP/files/*.orig exactly once
#   * $BACKUP/manifest.txt + $BACKUP/installed.txt drive ./rollback.sh
#   * no firmware, APK or vendor binary is shipped by this repository
#
# Requirements: adb (or $ADB), python3 (or python), rooted head unit,
#               adb over TCP. Cross compiler + stock AOSP HAL only if you
#               actually need to (re)build them.
#
# License: Apache-2.0
# ---------------------------------------------------------------------------
set -Eeuo pipefail

VERSION="1.0.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Git Bash/MSYS rewrites /system/... into C:/Program Files/Git/system/...
case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

ADB="${ADB:-adb}"
export ADB
APPLY=0
BACKUP_ONLY=0
SKIP_BUILD=0
SKIP_REBOOT=0
TARGET=""
BDADDR=""
CONFIG="config/local.properties"
HAL_SO=""
STOCK_SO=""
BACKUP="${BACKUP_DIR:-/data/local/aosp_bak}"

HAL_TARGETS=(
  /system/lib/hw/bluetooth.default.so
  /system/lib/hw/bluetooth.mt6735.so
  /system/vendor/lib/hw/bluetooth.default.so
  /system/vendor/lib/hw/bluetooth.mt6735.so
)
VENDOR_TARGETS=(
  /system/lib/libbt-vendor.so
  /system/vendor/lib/libbt-vendor.so
)
LEGACY_FILES=(
  /system/bin/brlinkd
  /system/vendor/lib/hw/bluetooth.blueangel.so
  /system/app/Bluetooth/Bluetooth.apk
  /system/app/Bluetooth/lib/arm/libbluetooth_jni.so
  /system/lib/libbluetooth_jni.so
)

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

  --apply            actually write to the head unit (default: dry-run)
  --backup-only      only create the backup, then exit
  --target IP:5555   override head-unit address
  --bdaddr MAC       override Bluetooth address (else from config / device)
  --config FILE      defaults to config/local.properties
  --hal-so FILE      use this already-patched bluetooth.default.so
  --stock-so FILE    stock AOSP HAL to patch (only needed if it is not built)
  --skip-build       never invoke hal/build.sh
  --skip-reboot      do not reboot at the end
  -h, --help         this text

Environment: ADB=/path/to/adb, BACKUP_DIR=/data/local/aosp_bak
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)        APPLY=1 ;;
    --backup-only)  BACKUP_ONLY=1 ;;
    --skip-build)   SKIP_BUILD=1 ;;
    --skip-reboot)  SKIP_REBOOT=1 ;;
    --target)       TARGET="${2:-}"; shift ;;
    --bdaddr)       BDADDR="${2:-}"; shift ;;
    --config)       CONFIG="${2:-}"; shift ;;
    --hal-so)       HAL_SO="${2:-}"; shift ;;
    --stock-so)     STOCK_SO="${2:-}"; shift ;;
    -h|--help)      usage; exit 0 ;;
    *)              die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

say "Geely R621 · DiPlay installer v$VERSION"
say "mode   : $([ "$APPLY" -eq 1 ] && echo APPLY || echo DRY-RUN)"
say "log    : ${LOG#$ROOT/}"

# ---------------------------------------------------------------------------
# 1. preflight
# ---------------------------------------------------------------------------
step "1/6 preflight"

command -v "$ADB" >/dev/null 2>&1 || die "adb not found (install platform-tools or set ADB=)"

PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "python3 not found"

[ -f "$CONFIG" ] || {
  warn "config not found: $CONFIG"
  if [ -f config/example.properties ]; then
    cp config/example.properties "$CONFIG"
    die "created $CONFIG — edit target / bdaddr / aosp_dir, then re-run"
  fi
  die "missing $CONFIG"
}

prop() {
  grep -E "^[[:space:]]*$1[[:space:]]*=" "$CONFIG" 2>/dev/null | tail -1 \
    | sed 's/^[^=]*=//' | tr -d '\r' | sed 's/[[:space:]]*$//' || true
}

[ -n "$TARGET" ]  || TARGET="$(prop target)"
[ -n "$BDADDR" ]  || BDADDR="$(prop bdaddr)"
AOSP_DIR="$(prop aosp_dir)";  AOSP_DIR="${AOSP_DIR:-./vendor/aosp51}"
DISABLE_PKGS="$(prop disable_packages)"
[ -n "$DISABLE_PKGS" ] || DISABLE_PKGS="com.ivt.bt,com.jsbd.btservice,ecarx.bluetooth.service,com.ecarx.btphone"

if [ -z "$TARGET" ] && [ -f tools/find_headunit.py ]; then
  info "no target configured, probing the local network ..."
  TARGET="$("$PY" tools/find_headunit.py --quiet 2>/dev/null | head -1 || true)"
fi
[ -n "$TARGET" ] || die "no target — set target= in $CONFIG or pass --target IP:5555"

info "adb    : $(command -v "$ADB")"
info "python : $PY"
info "target : $TARGET"
info "bdaddr : ${BDADDR:-(unchanged)}"
info "aosp   : $AOSP_DIR"

# ---------------------------------------------------------------------------
# 2. connect + root
# ---------------------------------------------------------------------------
step "2/6 connect"

"$ADB" connect "$TARGET" >/dev/null 2>&1 || true
for i in 1 2 3 4 5; do
  if "$ADB" -s "$TARGET" shell true >/dev/null 2>&1; then break; fi
  [ "$i" -lt 5 ] && sleep 2
done
"$ADB" -s "$TARGET" shell true >/dev/null 2>&1 || die "cannot reach $TARGET over adb"

ident="$("$ADB" -s "$TARGET" shell id 2>/dev/null | tr -d '\r')"
if ! printf '%s' "$ident" | grep -q 'uid=0'; then
  info "not root, trying 'adb root' ..."
  "$ADB" root >/dev/null 2>&1 || true
  sleep 3
  "$ADB" connect "$TARGET" >/dev/null 2>&1 || true
  ident="$("$ADB" -s "$TARGET" shell id 2>/dev/null | tr -d '\r')"
fi
info "shell  : ${ident:-unknown}"
printf '%s' "$ident" | grep -q 'uid=0' || warn "not uid=0 — deploy_hal.py will abort; enable adb root on the unit"

sh_()   { "$ADB" -s "$TARGET" shell "$@"; }

# Safely embed a command inside `sh -c '...'`. Without this, any single quote
# in the command (paths are quoted) terminates the outer string early and the
# device silently runs a truncated command — e.g. `cat` with no argument, which
# looks like success and yields an empty backup.
shquote() { printf '%s' "$1" | sed "s/'/'\\\\''/g"; }

root_() {
  local cmd
  cmd="$(shquote "$*")"
  "$ADB" -s "$TARGET" shell "su 0 sh -c '$cmd'"
}

# `su 0` is the portable form on this ROM; verify it works before trusting it.
if ! root_ "id" 2>/dev/null | grep -q 'uid=0'; then
  warn "'su 0' unavailable; falling back to plain shell (expect permission errors)"
  root_() { "$ADB" -s "$TARGET" shell "$*"; }
fi

# ---------------------------------------------------------------------------
# 3. backup (always, idempotent, never overwrites a good .orig)
# ---------------------------------------------------------------------------
step "3/6 backup -> $BACKUP"

root_ "mkdir -p '$BACKUP/files'"

backup_one() {
  local path="$1" key bak state
  key="_${path#/}"; key="${key//\//_}"
  bak="$BACKUP/files/$key.orig"
  state="$(root_ "if [ -f '$path' ]; then mkdir -p '$BACKUP/files'; [ -f '$bak' ] || cp -p '$path' '$bak' 2>/dev/null; if [ -f '$bak' ]; then echo saved; else echo failed; fi; else echo absent; fi" | tr -d '\r' | tr -d '\n')"
  case "$state" in
    saved)
      # record path|backup-name|mode so rollback.sh can put it back exactly
      root_ "printf '%s|%s|%s\n' '$path' '${bak##*/}' \"\$(stat -c %a '$path' 2>/dev/null || echo -)\" >> '$BACKUP/manifest.txt'"
      info "saved  $path"
      ;;
    absent) info "absent $path" ;;
    *)      die "backup failed for $path (permissions? /data full?)" ;;
  esac
}

for f in "${LEGACY_FILES[@]}" "${HAL_TARGETS[@]}" "${VENDOR_TARGETS[@]}"; do
  backup_one "$f"
done

# DiPlay app + data (needed by rollback.sh --restore-diplay)
root_ "if [ -f /system/app/DiPlay/DiPlay.apk ] && [ ! -f '$BACKUP/DiPlay_orig' ]; then cp -p /system/app/DiPlay/DiPlay.apk '$BACKUP/DiPlay_orig'; fi; true"
root_ "if [ -d /data/data/com.shihab.diplay ] && [ ! -d '$BACKUP/DiPlay_data_orig' ]; then cp -r /data/data/com.shihab.diplay '$BACKUP/DiPlay_data_orig'; fi; true"

printf '%s\n' "${HAL_TARGETS[@]}" "${VENDOR_TARGETS[@]}" \
  /system/app/Bluetooth/Bluetooth.apk \
  /system/app/Bluetooth/lib/arm/libbluetooth_jni.so \
  /system/lib/libbluetooth_jni.so > "$ROOT/.installed.list"
"$ADB" -s "$TARGET" push "$ROOT/.installed.list" "$BACKUP/installed.txt" >/dev/null 2>&1 || true
rm -f "$ROOT/.installed.list"

n_files="$(root_ "[ -d '$BACKUP/files' ] && ls '$BACKUP/files' | wc -l" | tr -d '\r ' || true)"
info "backup files: ${n_files:-0}"
root_ "ls -la '$BACKUP'" || true

if [ "$BACKUP_ONLY" -eq 1 ]; then
  step "done (backup only)"
  say "Rollback at any time:  ./rollback.sh --apply"
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. build inputs
# ---------------------------------------------------------------------------
step "4/6 build inputs"

VENDOR_SO="hal/build/libbt-vendor.so"
DEFAULT_SO="hal/build/bluetooth.default.so"

if [ ! -f "$VENDOR_SO" ]; then
  if [ "$SKIP_BUILD" -eq 1 ]; then
    die "missing $VENDOR_SO and --skip-build was given"
  fi
  info "building $VENDOR_SO ..."
  ( cd hal && bash build.sh ) || die "hal/build.sh failed — see hal/README.md"
fi

if [ -n "$HAL_SO" ]; then
  DEFAULT_SO="$HAL_SO"
  info "patched HAL supplied: $HAL_SO"
elif [ ! -f "$DEFAULT_SO" ]; then
  [ -n "$STOCK_SO" ] || STOCK_SO="$(prop stock_hal)"
  [ -n "$STOCK_SO" ] || die "no patched HAL: pass --stock-so /path/to/aosp/bluetooth.default.so (or build it yourself)"
  info "patching $STOCK_SO -> $DEFAULT_SO"
  "$PY" hal/patch_hal.py "$STOCK_SO" "$DEFAULT_SO"
fi

APK="$AOSP_DIR/Bluetooth.apk"
JNI="$AOSP_DIR/libbluetooth_jni.so"
[ -f "$APK" ] || die "missing $APK — extract it from AOSP 5.1 LMY48M (see README step 0)"
[ -f "$JNI" ] || die "missing $JNI — extract it from AOSP 5.1 LMY48M"

info "vendor : $(ls -l "$VENDOR_SO" | awk '{print $5}') bytes"
info "hal    : $(ls -l "$DEFAULT_SO" | awk '{print $5}') bytes"
info "apk    : $APK"
info "jni    : $JNI"

# ---------------------------------------------------------------------------
# 5. deploy
# ---------------------------------------------------------------------------
step "5/6 deploy"

DEPLOY_ARGS=(--config "$CONFIG" --target "$TARGET")
[ -n "$BDADDR" ] && DEPLOY_ARGS+=(--bdaddr "$BDADDR")
[ "$SKIP_REBOOT" -eq 1 ] && DEPLOY_ARGS+=(--skip-reboot)

if [ "$APPLY" -eq 0 ]; then
  "$PY" tools/deploy_hal.py "${DEPLOY_ARGS[@]}"
  step "dry-run complete"
  cat <<EOF
Nothing was written. Review the plan above, then run:

    ./install.sh --apply$([ "$SKIP_REBOOT" -eq 1 ] && echo " --skip-reboot")

To undo a real run later:

    ./rollback.sh --apply
EOF
  exit 0
fi

"$PY" tools/deploy_hal.py "${DEPLOY_ARGS[@]}" --apply || die "deploy_hal.py failed — backup is intact in $BACKUP"

# ---------------------------------------------------------------------------
# 6. wrap up
# ---------------------------------------------------------------------------
step "6/6 done"

cat <<EOF
Installed. Next:

  1. head unit  -> Settings -> Portable hotspot -> ON   (note SSID / password)
  2. iPhone     -> Wi-Fi -> join that hotspot
  3. DiPlay     -> mode "head-unit hotspot" -> Wireless Connect

If Bluetooth misbehaves after the reboot:

  ./rollback.sh --apply          # full restore of the stock Barrot/IVT stack
  ./rollback.sh --list           # inspect what is in $BACKUP first

Backup kept at: $BACKUP   (do NOT delete it)
Log:            ${LOG#$ROOT/}
EOF
