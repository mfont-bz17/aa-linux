#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DHU=${DHU:-}
CONFIG="$(dirname $DHU)/config/default_720p.ini"
USB=0
FAKETIME=1

usage() {
    cat <<EOF
Usage: $0 [--usb] [--config FILE] [--no-faketime]

Launch the separately installed Android Auto Desktop Head Unit.
  --usb              Connect through the aa-linux FunctionFS USB gadget
  --config FILE      Use a DHU configuration (default: $CONFIG)
  --no-faketime      Do not preload the local DHU test-time shim

If DHU is not found, install it from:
  https://developer.android.com/training/cars/testing/dhu
EOF
}

while (($#)); do
    case "$1" in
        --usb) USB=1 ;;
        --no-faketime) FAKETIME=0 ;;
        --config)
            (($# >= 2)) || { printf '%s\n' '--config requires a file' >&2; exit 2; }
            CONFIG=$2
            shift
            ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ -z "$DHU" ]]; then
    candidates=(
        "$ROOT/desktop-head-unit"
        "${ANDROID_SDK_ROOT:-}/extras/google/auto/desktop-head-unit"
        "${ANDROID_HOME:-}/extras/google/auto/desktop-head-unit"
        "$HOME/Android/Sdk/extras/google/auto/desktop-head-unit"
    )
    for candidate in "${candidates[@]}"; do
        if [[ -x "$candidate" ]]; then
            DHU=$candidate
            break
        fi
    done
fi

if [[ -z "$DHU" || ! -x "$DHU" ]]; then
    cat >&2 <<EOF
Desktop Head Unit was not found.

Download "Android Auto Desktop Head Unit Emulator" using Android Studio's SDK
Manager, or install it with sdkmanager "extras;google;auto". Then set:

  DHU=/path/to/desktop-head-unit $0

See: https://developer.android.com/training/cars/testing/dhu
EOF
    exit 1
fi

args=("$DHU" --config "$CONFIG")
if ((USB)); then
    args+=(--usb)
else
    args+=(--adb=5277)
fi

if ((FAKETIME)); then
    shim="$ROOT/.cache/faketime_shim.so"
    mkdir -p "${shim%/*}"
    if [[ ! -x "$shim" || "$ROOT/aa-linux/certs/dev/faketime_shim.c" -nt "$shim" ]]; then
        command -v cc >/dev/null || { printf '%s\n' 'A C compiler is required for the DHU test-time shim.' >&2; exit 1; }
        cc -shared -fPIC -o "$shim" "$ROOT/aa-linux/certs/dev/faketime_shim.c" -ldl
    fi
    exec env LD_PRELOAD="$shim" "${args[@]}"
fi

exec "${args[@]}"
