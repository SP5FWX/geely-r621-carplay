#!/usr/bin/env bash
# Cross-compile the MT6620 vendor library for Android 5.1 (32-bit ARM).
#
# Usage:
#   ./build.sh                       # uses arm-linux-gnueabi-gcc from PATH
#   ./build.sh /opt/arm/bin/arm-linux-gnueabi-gcc
#   BT_BDADDR_DEFAULT=AA:BB:CC:DD:EE:FF ./build.sh   # bake in an address
#
# The --hash-style=both flag is NOT optional: the Android 5.1 linker looks up
# symbols through DT_HASH. A GNU-hash-only .so loads "successfully" but every
# dlsym() returns NULL, which is painful to diagnose.

set -euo pipefail

CC="${1:-arm-linux-gnueabi-gcc}"
SRC="$(cd "$(dirname "$0")" && pwd)/bt_vendor_mtk.c"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)/build"
OUT="$OUT_DIR/libbt-vendor.so"

if ! command -v "$CC" >/dev/null 2>&1; then
    echo "error: compiler not found: $CC" >&2
    echo "install gcc-arm-linux-gnueabi (Debian/Ubuntu) or pass the full path" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"

EXTRA_DEFS=""
if [[ -n "${BT_BDADDR_DEFAULT:-}" ]]; then
    EXTRA_DEFS="-DBT_BDADDR_DEFAULT=\"${BT_BDADDR_DEFAULT}\""
    echo "[*] baking default BD_ADDR: ${BT_BDADDR_DEFAULT}"
fi

echo "[*] compiler: $CC"
"$CC" -shared -fPIC -O2 -Wall -Wextra \
    -fno-stack-protector \
    -Wl,--hash-style=both \
    -Wl,-soname,libbt-vendor.so \
    $EXTRA_DEFS \
    -o "$OUT" "$SRC"

echo "[*] built: $OUT"
echo "[*] size : $(stat -c%s "$OUT" 2>/dev/null || wc -c <"$OUT") bytes"

echo "[*] exported interface:"
readelf -sW "$OUT" | grep -i BLUETOOTH_VENDOR_LIB_INTERFACE || {
    echo "error: BLUETOOTH_VENDOR_LIB_INTERFACE not exported" >&2
    exit 1
}

echo "[*] hash tables:"
readelf -d "$OUT" | grep -E 'HASH' || {
    echo "error: no HASH entry; Android 5.1 linker will fail to resolve symbols" >&2
    exit 1
}

cat <<'EOF'

Next steps:
  1. adb push build/libbt-vendor.so /system/lib/libbt-vendor.so
  2. adb push build/libbt-vendor.so /system/vendor/lib/libbt-vendor.so
  3. echo AA:BB:CC:DD:EE:FF > /data/local/etc/bt_bdaddr   (optional)
  4. chmod 644 /system/lib/libbt-vendor.so
EOF
