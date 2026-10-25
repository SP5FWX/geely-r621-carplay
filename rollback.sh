#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Geely R621 · DiPlay wireless CarPlay — one-click rollback
#
#   ./rollback.sh --list            show what the backup contains (read-only)
#   ./rollback.sh --apply           restore the stock Barrot/IVT Bluetooth stack
#   ./rollback.sh --apply --restore-diplay
#
# What it does (mirror image of install.sh):
#   * restores every file recorded in $BACKUP/manifest.txt, with its mode
#   * deletes the files install.sh put there that had no original
#   * re-enables the stock Bluetooth packages, resets /data/misc/bluedroid
#   * optional: restore the official DiPlay APK + its data
#
# Refuses to touch anything unless the manifest looks sane, and never
# deletes a file it has no record of.
#
# License: Apache-2.0
# ---------------------------------------------------------------------------
set -Eeuo pipefail

VERSION="1.0.0"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

case "$(uname -s 2>/dev/null || echo unknown)" in
  MINGW*|MSYS*|CYGWIN*) export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ;;
esac

ADB="${ADB:-adb}"
export ADB
APPLY=0
LIST_ONLY=0
SKIP_REBOOT=0
RESTORE_DIPLAY=0
ASSUME_YES=0
TARGET=""
CONFIG="config/local.properties"
BACKUP="${BACKUP_DIR:-/data/local/aosp_bak}"

say()  { printf '%s\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m[!] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Usage: ./rollback.sh --apply [options]

  --apply             perform the restore (required for any write)
  --list              print the backup manifest and exit
  --restore-diplay    also restore DiPlay.apk and its /data
  --target IP:5555    override head-unit address
  --config FILE       defaults to config/local.properties
  --skip-reboot       do not reboot at the end
  --yes               skip the confirmation prompt

Environment: ADB=/path/to/adb, BACKUP_DIR=/data/local/aosp_bak
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)          APPLY=1 ;;
    --list)           LIST_ONLY=1 ;;
    --restore-diplay) RESTORE_DIPLAY=1 ;;
    --skip-reboot)    SKIP_REBOOT=1 ;;
    --yes|-y)         ASSUME_YES=1 ;;
    --target)         TARGET="${2:-}"; shift ;;
    --config)         CONFIG="${2:-}"; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

[ "$APPLY" -eq 1 ] || [ "$LIST_ONLY" -eq 1 ] || { usage; exit 2; }

mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/rollback-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

say "Geely R621 · rollback v$VERSION"

command -v "$ADB" >/dev/null 2>&1 || die "adb not found (set ADB=)"

if [ -f "$CONFIG" ]; then
  [ -n "$TARGET" ] || TARGET="$(grep -E '^[[:space:]]*target[[:space:]]*=' "$CONFIG" \
    | tail -1 | sed 's/^[^=]*=//' | tr -d '\r' | sed 's/[[:space:]]*$//' || true)"
fi
[ -n "$TARGET" ] || die "no target — pass --target IP:5555 or set target= in $CONFIG"

step "1/5 connect"
"$ADB" connect "$TARGET" >/dev/null 2>&1 || true
for i in 1 2 3 4 5; do
  "$ADB" -s "$TARGET" shell true >/dev/null 2>&1 && break
  [ "$i" -lt 5 ] && sleep 2
done
"$ADB" -s "$TARGET" shell true >/dev/null 2>&1 || die "cannot reach $TARGET over adb"

sh_()   { "$ADB" -s "$TARGET" shell "$@"; }

# Same quoting guard as install.sh: a bare `'` in the payload would truncate
# the `sh -c '...'` string and silently run a partial command.
shquote() { printf '%s' "$1" | sed "s/'/'\\\\''/g"; }

root_() {
  local cmd
  cmd="$(shquote "$*")"
  "$ADB" -s "$TARGET" shell "su 0 sh -c '$cmd'"
}

ident="$(sh_ id 2>/dev/null | tr -d '\r')"
if ! printf '%s' "$ident" | grep -q 'uid=0'; then
  info "not root, trying 'adb root' ..."
  "$ADB" root >/dev/null 2>&1 || true
  sleep 3
  "$ADB" connect "$TARGET" >/dev/null 2>&1 || true
  ident="$(sh_ id 2>/dev/null | tr -d '\r')"
fi
info "shell: ${ident:-unknown}"
printf '%s' "$ident" | grep -q 'uid=0' || warn "not uid=0 — restore will likely fail"

if ! root_ "id" 2>/dev/null | grep -q 'uid=0'; then
  warn "'su 0' unavailable; falling back to plain shell"
  root_() { "$ADB" -s "$TARGET" shell "$*"; }
fi

# ---------------------------------------------------------------------------
# 2. load the backup
# ---------------------------------------------------------------------------
step "2/5 backup inventory"

MANIFEST="$(mktemp)"; INSTALLED="$(mktemp)"; RESTORED="$(mktemp)"
trap 'rm -f "$MANIFEST" "$INSTALLED" "$RESTORED"' EXIT

root_ "cat '$BACKUP/manifest.txt' 2>/dev/null" | tr -d '\r' > "$MANIFEST" || true
root_ "cat '$BACKUP/installed.txt' 2>/dev/null" | tr -d '\r' > "$INSTALLED" || true

if [ ! -s "$MANIFEST" ]; then
  warn "no manifest at $BACKUP/manifest.txt"
  warn "if the backup was made by hand, follow docs/rollback.md instead"
  [ "$LIST_ONLY" -eq 1 ] && exit 0
  die "refusing to restore without a manifest (nothing would be reversible)"
fi

info "manifest entries: $(wc -l < "$MANIFEST" | tr -d ' ')"
say ""
say "  PATH                                        BACKUP FILE / MODE"
say "  ------------------------------------------  ------------------------"
while IFS='|' read -r p n m; do
  [ -n "$p" ] || continue
  printf '  %-42s  %s  %s\n' "$p" "$n" "${m:--}"
done < "$MANIFEST"

if [ "$LIST_ONLY" -eq 1 ]; then
  say ""
  say "installed by install.sh:"
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    if grep -Fqx "$p" "$MANIFEST" >/dev/null 2>&1; then
      say "  restore  $p"
    else
      say "  remove   $p"
    fi
  done < "$INSTALLED"
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. confirm
# ---------------------------------------------------------------------------
step "3/5 confirm"

say "This will restore the stock Barrot/IVT Bluetooth stack and reboot the unit."
say "Files created by install.sh with no original will be deleted."
if [ "$RESTORE_DIPLAY" -eq 1 ]; then
  say "DiPlay APK + /data/data/com.shihab.diplay will also be restored."
fi
say ""
say "Backup to be used: $BACKUP"

if [ "$ASSUME_YES" -eq 0 ]; then
  if [ ! -t 0 ]; then
    die "no interactive terminal — re-run with --yes to confirm"
  fi
  printf 'Type "restore" to continue: '
  read -r answer
  [ "$answer" = "restore" ] || die "aborted"
fi

# ---------------------------------------------------------------------------
# 4. restore
# ---------------------------------------------------------------------------
step "4/5 restore files"

root_ "mount -o rw,remount /system" || warn "remount returned non-zero (may already be rw)"
root_ "setprop ctl.stop brlinkd; sleep 1; true"
root_ "setprop ctl.stop bluetoothd 2>/dev/null; true"

while IFS='|' read -r p n m; do
  [ -n "$p" ] || continue
  if grep -Fqx "$p" "$RESTORED" >/dev/null 2>&1; then continue; fi
  printf '%s\n' "$p" >> "$RESTORED"

  if root_ "[ -f '$BACKUP/files/$n' ] && echo yes" | grep -q yes; then
    root_ "cp -p '$BACKUP/files/$n' '$p'"
    case "$m" in
      ''|-)
        # stat unavailable on some 5.1 ROMs: executables in /bin need 755
        case "$p" in
          */bin/*) root_ "chmod 755 '$p' 2>/dev/null; true" ;;
          *)       root_ "chmod 644 '$p' 2>/dev/null; true" ;;
        esac
        ;;
      *) root_ "chmod '$m' '$p' 2>/dev/null; true" ;;
    esac
    info "restored $p"
  else
    warn "backup missing for $p (expected $BACKUP/files/$n)"
  fi
done < "$MANIFEST"

say ""
say "removing files that had no original:"
while IFS= read -r p; do
  [ -n "$p" ] || continue
  grep -Fqx "$p" "$RESTORED" >/dev/null 2>&1 && continue
  if root_ "[ -e '$p' ] && echo yes" | grep -q yes; then
    # keep a copy in the backup area instead of destroying it outright
    key="_$(printf '%s' "$p" | sed 's#^/##; s#/#_#g')"
    root_ "mkdir -p '$BACKUP/replaced'; cp -p '$p' '$BACKUP/replaced/${key}.removed' 2>/dev/null; true"
    root_ "rm -f '$p' 2>/dev/null || mv '$p' '$BACKUP/replaced/' 2>/dev/null; true"
    info "removed  $p"
  fi
done < "$INSTALLED"

# /dev node: install.sh renamed ivt_stpbt -> stpbt for the AOSP HAL
root_ "if [ -e /dev/stpbt ] && [ ! -e /dev/ivt_stpbt ]; then mv /dev/stpbt /dev/ivt_stpbt; fi; true"
root_ "chmod 666 /dev/ivt_stpbt /dev/stpwmt 2>/dev/null; true"

# stock Bluetooth packages back on
PKGS="com.ivt.bt com.jsbd.btservice ecarx.bluetooth.service com.ecarx.btphone"
for pkg in $PKGS; do
  sh_ "pm enable $pkg" >/dev/null 2>&1 && info "enabled $pkg" || true
done

if [ "$RESTORE_DIPLAY" -eq 1 ]; then
  if root_ "[ -f '$BACKUP/DiPlay_orig' ] && echo yes" | grep -q yes; then
    root_ "cp -p '$BACKUP/DiPlay_orig' /system/app/DiPlay/DiPlay.apk; chmod 644 /system/app/DiPlay/DiPlay.apk"
    sh_ "am force-stop com.shihab.diplay" >/dev/null 2>&1 || true
    if root_ "[ -d '$BACKUP/DiPlay_data_orig' ] && echo yes" | grep -q yes; then
      root_ "rm -rf /data/data/com.shihab.diplay; cp -r '$BACKUP/DiPlay_data_orig' /data/data/com.shihab.diplay; chown -R 10042:10042 /data/data/com.shihab.diplay"
    fi
    info "DiPlay restored"
  else
    warn "no DiPlay backup found, skipped"
  fi
fi

# stale Bluedroid state would otherwise resurrect AOSP config
root_ "rm -rf /data/misc/bluedroid; mkdir -p /data/misc/bluedroid"
root_ "chown bluetooth:bluetooth /data/misc/bluedroid; chmod 770 /data/misc/bluedroid"
root_ "sync"

# ---------------------------------------------------------------------------
# 5. verify + reboot
# ---------------------------------------------------------------------------
step "5/5 verify"

info "brlinkd : $(sh_ 'ps | grep brlinkd | grep -v grep' 2>/dev/null | tr -d '\r' | head -1)"
info "nodes   : $(sh_ 'ls -la /dev/ivt_stpbt /dev/stpbt 2>/dev/null' 2>/dev/null | tr -d '\r' | tr '\n' ' ')"

if [ "$SKIP_REBOOT" -eq 0 ]; then
  say ""
  say "rebooting ..."
  root_ "reboot" || true
  say "after boot, check:  adb logcat -d | grep -E 'BARROT|bse_stack' | tail"
else
  say ""
  say "skipped reboot — power-cycle the unit before validating"
fi

say ""
say "Rollback log: ${LOG#$ROOT/}"
say "Stock Bluetooth should be back. If the unit no longer boots, see docs/rollback.md §5."
