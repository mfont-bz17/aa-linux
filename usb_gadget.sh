#!/usr/bin/env bash
# usb_gadget.sh — create/destroy the configfs + FunctionFS USB gadget the DHU sees.
# VID 0x18d1 / PID 0x2d01 (Android accessory mode), one 0xFF/0xFF/0x00 vendor
# interface with bulk IN/OUT endpoints. Use --dummy (dummy_hcd) for single-machine tests.

set -euo pipefail
NAME=aa_linux
FUNCTION=ffs.aa
VID=0x18d1
PID=0x2d01
FFS_DIR=/dev/$NAME
GADGET_DIR=/sys/kernel/config/usb_gadget/$NAME
CONFIG_DIR=$GADGET_DIR/configs/c.1
FUNC_DIR=$GADGET_DIR/functions/$FUNCTION
WAIT_TIMEOUT_S=60

DRY=0
USE_DUMMY=0
NO_WAIT=0
UDC=
MODE=

usage() {
    cat <<EOF
Usage:
  sudo $0 start [--dummy] [--udc UDC] [--no-wait]
  sudo $0 stop
  $0 start --dry-run        # print commands, do nothing
EOF
    exit 1
}

log() { echo "[usb_gadget] $*"; }

# run a command (print it under --dry-run); run_ok tolerates failures
run() {
    if [ "$DRY" -eq 1 ]; then
        printf '> %s\n' "$*"
    else
        "$@"
    fi
}
run_ok() { run "$@" || true; }

write_sys() { printf '%s\n' "$2" | run tee "$1"; }

find_udc() {
    if [ -n "$UDC" ]; then
        echo "$UDC"
        return 0
    fi
    if [ "$USE_DUMMY" -eq 1 ]; then
        if [ -d /sys/class/udc/dummy_udc.0 ]; then
            echo dummy_udc.0
            return 0
        fi
        if [ "$DRY" -eq 1 ]; then
            echo dummy_udc.0
            return 0
        fi
        log "ERROR: dummy_udc.0 not present (modprobe dummy_hcd?)"
        return 1
    fi
    local udc
    udc=$(ls /sys/class/udc/ 2>/dev/null | head -n1) || true
    if [ -n "$udc" ]; then
        echo "$udc"
        return 0
    fi
    if [ "$DRY" -eq 1 ]; then
        echo "<auto-detected-udc>"
        return 0
    fi
    log "ERROR: no UDC found in /sys/class/udc/ (add --dummy for a virtual one)"
    return 1
}

load_modules() {
    run_ok modprobe libcomposite
    run_ok modprobe usb_f_fs
    run_ok modprobe dummy_hcd
}

mount_configfs() {
    [ -d /sys/kernel/config ] || run mkdir -p /sys/kernel/config
    mountpoint -q /sys/kernel/config || run mount -t configfs configfs /sys/kernel/config
}

create_gadget() {
    if [ -d "$GADGET_DIR" ]; then
        log "gadget $NAME exists, tearing down first"
        teardown_gadget
    fi

    run mkdir -p "$GADGET_DIR"
    write_sys "$GADGET_DIR/idVendor" "$VID"
    write_sys "$GADGET_DIR/idProduct" "$PID"
    write_sys "$GADGET_DIR/bcdUSB" 0x0200

    run mkdir -p "$GADGET_DIR/strings/0x409"
    write_sys "$GADGET_DIR/strings/0x409/manufacturer" Google
    write_sys "$GADGET_DIR/strings/0x409/product" Android
    write_sys "$GADGET_DIR/strings/0x409/serialnumber" 0123456789ABCDEF

    run mkdir -p "$CONFIG_DIR/strings/0x409"
    write_sys "$CONFIG_DIR/strings/0x409/configuration" "AA Linux USB"

    run mkdir -p "$FUNC_DIR"
    run ln -s "$FUNC_DIR" "$CONFIG_DIR/$FUNCTION"
}

mount_ffs() {
    run mkdir -p "$FFS_DIR"
    if ! mountpoint -q "$FFS_DIR"; then
        run mount -t functionfs aa "$FFS_DIR" -o mode=0666
        run chown -R "$(id -un):$(id -gn)" "$FFS_DIR"
        run chmod -R g+rwX "$FFS_DIR"
    fi
}

wait_ready() {
    if [ "$NO_WAIT" -eq 1 ] || [ "$DRY" -eq 1 ]; then
        [ "$DRY" -eq 1 ] && log "(would wait for FunctionFS descriptors, timeout ${WAIT_TIMEOUT_S}s)"
        return 0
    fi
    log "waiting for the client to register FunctionFS descriptors ..."
    log "  (start the phone side in another shell:  sudo ./aa-linux.sh usb)"
    local i
    for ((i = 0; i < WAIT_TIMEOUT_S; i++)); do
        if [ -f "$FFS_DIR/ep1" ] || [ "$(cat "$FUNC_DIR/ready" 2>/dev/null || true)" = 1 ]; then
            log "FunctionFS function is ready"
            return 0
        fi
        sleep 1
    done
    log "ERROR: timed out waiting for the FunctionFS function"
    return 1
}

bind_udc() {
    local udc
    udc=$(find_udc)
    write_sys "$GADGET_DIR/UDC" "$udc"
    log "bound gadget to UDC $udc"
}

teardown_gadget() {
    [ -s "$GADGET_DIR/UDC" ] && printf '\n' | run_ok tee "$GADGET_DIR/UDC"
    run_ok umount "$FFS_DIR"
    run_ok rm -f "$CONFIG_DIR/$FUNCTION"
    run_ok rmdir "$FUNC_DIR" "$CONFIG_DIR/strings/0x409" "$CONFIG_DIR" \
        "$GADGET_DIR/strings/0x409" "$GADGET_DIR"
}

do_start() {
    log "setting up USB gadget $NAME (VID $VID, PID $PID)"
    load_modules
    mount_configfs
    create_gadget
    mount_ffs
    wait_ready
    bind_udc
    log "gadget up. Check: lsusb | grep 18d1:2d01"
    log "Run the phone side with:  sudo ./aa-linux.sh usb"
    log "Then connect a separately obtained Desktop Head Unit with --usb."
}

do_stop() {
    log "tearing down USB gadget $NAME"
    if [ -d "$GADGET_DIR" ]; then
        teardown_gadget
    else
        run_ok umount "$FFS_DIR"
    fi
    log "done"
}

ORIG_ARGS=("$@")
while [ $# -gt 0 ]; do
    case "$1" in
        start) MODE=start ;;
        stop) MODE=stop ;;
        --dry-run) DRY=1 ;;
        --dummy) USE_DUMMY=1 ;;
        --no-wait) NO_WAIT=1 ;;
        --udc) UDC=$2; shift ;;
        -h|--help) usage ;;
        *) usage ;;
    esac
    shift
done

if [ "$(id -u)" -ne 0 ] && [ "$DRY" -eq 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        exec sudo "$0" "${ORIG_ARGS[@]}"
    else
        log "ERROR: must run as root"
        exit 1
    fi
fi

case "$MODE" in
    start) do_start ;;
    stop) do_stop ;;
    *) usage ;;
esac
