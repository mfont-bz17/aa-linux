#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
DEV_CERT="$ROOT/aa-linux/certs/dev/server_cert.pem"
DEV_KEY="$ROOT/aa-linux/certs/dev/server_key.pem"

usage() {
    cat <<EOF
Usage: $0 COMMAND [OPTIONS]

Phone-side commands:
  tcp [OPTIONS]          Listen for the DHU over TCP (default display: test)
  usb [OPTIONS]          Same as tcp over the FunctionFS USB transport
  wireless [OPTIONS]     Connect to a real car (default display: test)
  self-test              Run local protocol tests
  dev-cert               Check the local DHU test identity
  desktop               Start a virtual Xvfb display on :99 (1280x720x24) and run the DHU over TCP
  dev-desktop           Start a Xephyr instance on :99 (1280x720) with the workspace window manager
  scan-bt [SECONDS]      Scan for Bluetooth devices to find the car's MAC
  gadget-start           Start the dummy_hcd USB gadget (root required)
  gadget-stop            Stop the dummy_hcd USB gadget (root required)

TLS defaults to the local DHU-only test identity. Override with --cert and --key
for a real head unit. The development identity does not work with real cars.
EOF
}

_run_aa_linux() {
    exec "$PYTHON" -m aa-linux --cert "$DEV_CERT" --key "$DEV_KEY" "$@"
}

_display_arg_present() {
    for arg in "$@"; do
        [[ "$arg" == --display* || "$arg" == -d ]] && return 0
    done
    return 1
}

_display_wait() {
    local display=$1 tries=${2:-50}
    for ((i = 0; i < tries; i++)); do
        if DISPLAY="$display" xrandr -q >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.1
    done
    return 1
}

if (($# == 0)); then
    usage
    exit 0
fi

command=$1
shift

case "$command" in
    tcp|usb|wireless)
        transport=tcp
        [[ "$command" == usb ]] && transport=usb
        [[ "$command" == wireless ]] && transport=wireless
        if _display_arg_present "$@"; then
            _run_aa_linux --transport "$transport" "$@"
        fi
        _run_aa_linux --transport "$transport" --display test "$@"
        ;;
    desktop)
        if ! command -v Xvfb >/dev/null 2>&1; then
            printf '%s\n' 'Xvfb not found (sudo apt install xvfb).' >&2
            exit 1
        fi
        display=":99"
        setsid Xvfb "$display" -screen 0 1280x720x24 -nolisten tcp >/dev/null 2>&1 &
        xvfb_pid=$!
        if ! _display_wait "$display"; then
            printf '%s\n' "Xvfb did not start on $display." >&2
            kill -- -"$xvfb_pid" 2>/dev/null || true
            exit 1
        fi
        # Start the workspace window manager (openbox) on the virtual display
        (cd "$ROOT" && exec setsid "$ROOT/openbox-desktop.sh") >/dev/null 2>&1 &
        wm_pid=$!
        # Run aa-linux on the openbox desktop's D-Bus session so its services
        # (e.g. org.aalinux.sensors) share the bus with the desktop apps.
        dbus_file="$ROOT/openbox-desktop/runtime/dbus-address"
        for ((i = 0; i < 50; i++)); do
            if [[ -s "$dbus_file" ]]; then
                DBUS_SESSION_BUS_ADDRESS=$(<"$dbus_file")
                export DBUS_SESSION_BUS_ADDRESS
                break
            fi
            sleep 0.1
        done
        cleanup() {
            kill -- -"$wm_pid" 2>/dev/null || true
            kill -- -"$xvfb_pid" 2>/dev/null || true
        }
        trap cleanup EXIT INT TERM
        "$PYTHON" -m aa-linux --cert "$DEV_CERT" --key "$DEV_KEY" \
            --transport tcp --display "${display}.0+0,0" "$@"
        ;;
    dev-desktop)
        if ! command -v Xephyr >/dev/null 2>&1; then
            printf '%s\n' 'Xephyr not found (sudo apt install xephyr).' >&2
            exit 1
        fi
        display=":99"
        setsid Xephyr "$display" -screen 1280x720 -br -ac -nolisten tcp >/dev/null 2>&1 &
        xephyr_pid=$!
        if ! _display_wait "$display"; then
            printf '%s\n' "Xephyr did not start on $display." >&2
            kill -- -"$xephyr_pid" 2>/dev/null || true
            exit 1
        fi
        # Start the workspace window manager (openbox) on the Xephyr display
        (cd "$ROOT" && exec setsid "$ROOT/openbox-desktop.sh") >/dev/null 2>&1 &
        wm_pid=$!
        cleanup() {
            kill -- -"$wm_pid" 2>/dev/null || true
            kill -- -"$xephyr_pid" 2>/dev/null || true
        }
        trap cleanup EXIT INT TERM
        wait "$wm_pid"
        ;;
    self-test)
        "$PYTHON" -m unittest discover -s "$ROOT/tests"
        exec "$PYTHON" -m aa-linux.wireless --self-test
        ;;
    dev-cert)
        [[ -r "$DEV_CERT" && -r "$DEV_KEY" ]] || {
            printf '%s\n' 'Local DHU test identity is incomplete.' >&2
            exit 1
        }
        openssl x509 -in "$DEV_CERT" -noout >/dev/null
        openssl pkey -in "$DEV_KEY" -noout >/dev/null
        printf '%s\n' 'Local DHU test certificate and key are readable.'
        ;;
    scan-bt)
        seconds=${1:-10}
        command -v bluetoothctl >/dev/null || {
            printf '%s\n' 'bluetoothctl not found (install bluez).' >&2
            exit 1
        }
        printf 'Scanning for Bluetooth devices for %s seconds...\n' "$seconds"
        {
            printf 'scan on\n'
            sleep "$seconds"
            printf 'scan off\n'
            printf 'devices\n'
            printf 'quit\n'
        } | bluetoothctl || true
        ;;
    gadget-start)
        exec sudo "$ROOT/usb_gadget.sh" --dummy start
        ;;
    gadget-stop)
        exec sudo "$ROOT/usb_gadget.sh" --dummy stop
        ;;
    help|-h|--help)
        usage
        ;;
    *)
        printf 'Unknown command: %s\n\n' "$command" >&2
        usage >&2
        exit 2
        ;;
esac
