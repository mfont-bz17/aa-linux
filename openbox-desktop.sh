#!/bin/bash
# Usage: openbox-desktop.sh  [-- any openbox args]
set -e
WS=$(pwd)/openbox-desktop

export HOME="$WS/aa-linux-home"
mkdir -p $HOME
[ -L "$HOME/.config" ] || ln -s "$WS/config" "$HOME/.config"

export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME"
export XDG_DATA_DIRS="$WS:$WS/.local/share:/usr/local/share:/usr/share"
# Remember the real session's runtime dir before we isolate XDG_RUNTIME_DIR
# below: the current session's PipeWire sockets live there and workspace apps
# should still play audio through it (see the PIPEWIRE_*/PULSE_* exports).
# AA_WS_SESSION_RUNTIME survives the dbus-run-session re-exec.
SESSION_RUNTIME_DIR="${AA_WS_SESSION_RUNTIME:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}}"
export AA_WS_SESSION_RUNTIME="$SESSION_RUNTIME_DIR"

# Isolate runtime sockets (gvfs, keyring, portals) from the real session's
# /run/user/1000 — otherwise gvfsd-fuse collides with the live session.
export XDG_RUNTIME_DIR="$WS/runtime"
[ -d "$XDG_RUNTIME_DIR" ] || mkdir -p -m 0700 "$XDG_RUNTIME_DIR"

# Use the current session's PipeWire: clients locate the native server via
# PIPEWIRE_RUNTIME_DIR and the PulseAudio-compat server via PULSE_SERVER
# (+ PULSE_COOKIE for the shared auth cookie), all of which default to
# $XDG_RUNTIME_DIR — isolated above. Point them at the real session's runtime
# dir instead. No-op when that dir is absent (no session PipeWire running).
if [ -d "$SESSION_RUNTIME_DIR" ]; then
  export PIPEWIRE_RUNTIME_DIR="$SESSION_RUNTIME_DIR"
  export PULSE_SERVER="unix:$SESSION_RUNTIME_DIR/pulse/native"
  export PULSE_COOKIE="$SESSION_RUNTIME_DIR/pulse/.config"
fi

# Force X11 backend (Wayland -> X11) for all GTK/QT apps including menu launches
export DISPLAY=:99
export QT_QPA_PLATFORM=xcb
export GDK_BACKEND=x11
export GTK_BACKEND=x11
export MOZ_ENABLE_WAYLAND=0
export CLUTTER_BACKEND=x11

# Source workspace environment if present (same vars, kept for openbox-session compat)
[ -f "$WS/config/environment" ] && . "$WS/config/environment"

# Re-exec under an isolated D-Bus session so every process in this workspace
# (autostart, openbox, and the GNOME/GTK apps) uses the workspace dconf
# database ($WS/.config/dconf/user) instead of the main session's.
# NOTE: the exports above MUST happen before this, so the fresh bus daemon
# (and the dconf-service auto-activated on it) inherits the workspace env.
if [ -z "$OPENBOX_WS_BUS" ]; then
  export OPENBOX_WS_BUS=1
  exec dbus-run-session -- "$0" "$@"
fi

# Publish this isolated session bus so sibling processes (e.g. aa-linux) can
# join the same D-Bus session as the desktop apps.
echo "$DBUS_SESSION_BUS_ADDRESS" > "$XDG_RUNTIME_DIR/dbus-address"

# Push the workspace env into the bus daemon so ANY service that is
# D-Bus-activated later (not just dconf) inherits it too.
command -v dbus-update-activation-environment >/dev/null 2>&1 && \
  dbus-update-activation-environment DISPLAY XDG_CONFIG_HOME XDG_DATA_HOME \
    XDG_DATA_DIRS XDG_RUNTIME_DIR HOME QT_QPA_PLATFORM GDK_BACKEND GTK_BACKEND \
    MOZ_ENABLE_WAYLAND CLUTTER_BACKEND LANG \
    PIPEWIRE_RUNTIME_DIR PULSE_SERVER PULSE_COOKIE

# Start dconf-service EXPLICITLY on this fresh bus instead of relying on
# D-Bus auto-activation. GSettings then finds the name already registered,
# so apps never block on activation + the db file lock on first use.
if command -v dconf-service >/dev/null 2>&1; then
  dconf-service &
elif [ -x /usr/libexec/dconf-service ]; then
  /usr/libexec/dconf-service &
fi

# Pre-warm dconf-service with a read of the color-scheme key (prefer-dark /
# prefer-light) so the first real GSettings call from any app finds the
# service ready.
dconf read /org/gnome/desktop/interface/color-scheme >/dev/null 2>&1 || true

# Provide org.freedesktop.secrets on THIS bus. Without it, xdg-desktop-portal
# blocks ~25s on the D-Bus activation timeout every time it initializes.
# Unset the real session's keyring sockets first, or the daemon refuses to
# start a workspace-local instance.
unset GNOME_KEYRING_CONTROL SSH_AUTH_SOCK
if command -v gnome-keyring-daemon >/dev/null 2>&1; then
  eval "$(gnome-keyring-daemon --start --components=secrets 2>/dev/null)"
fi

[ -x "$WS/config/autostart" ] && "$WS/config/autostart" &

# Explicit config file — no XDG_CONFIG_HOME needed
exec openbox --config-file "$WS/config/rc.xml" "$@"

