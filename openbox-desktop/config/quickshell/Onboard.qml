import QtQuick
import Quickshell
import Quickshell.Io

// On-screen keyboard toggle, driven over D-Bus.
//
// A tiny python helper (`scripts/onboard-watch`, dbus-fast) subscribes to
// onboard's `Visible` property and prints ON/OFF on every change — no
// polling. The icon follows reality no matter how the keyboard was shown
// or hidden (button, status icon, other clients).
// Clicking calls ToggleVisible — no pkill, no process race.
BarModule {
    id: root

    readonly property bool onboardOn: _onboardOn
    property bool _onboardOn: false

    icon: "󰌌"
    iconColor: root.onboardOn ? Theme.accent : Qt.alpha(Theme.fg, 0.45)

    // Keep Onboard's color scheme in sync with the desktop palette. The
    // helper renders the template and bounces its gsettings key so Onboard
    // reloads without being restarted.
    FileView {
        id: paletteWatch
        path: Theme.configDir + "/theme/colors.ini"
        watchChanges: true
        onFileChanged: {
            reload()
            onboardThemeTimer.restart()
        }
        onLoaded: onboardThemeTimer.restart()
    }

    Timer {
        id: onboardThemeTimer
        interval: 200
        onTriggered: Quickshell.execDetached([
            Theme.configDir + "/scripts/onboard-theme"])
    }

    Process {
        id: watcher
        command: [Theme.configDir + "/scripts/onboard-watch"]
        running: true
        stdout: SplitParser {
            onRead: line => {
                const t = line.trim()
                if (t === "ON")
                    root._onboardOn = true
                else if (t === "OFF")
                    root._onboardOn = false
            }
        }
        // the helper exits if the bus drops; respawn it (debounced)
        onRunningChanged: {
            if (!running)
                respawnTimer.restart()
        }
    }

    Timer {
        id: respawnTimer
        interval: 1000
        onTriggered: watcher.running = true
    }

    onClicked: Quickshell.execDetached([
        "dbus-send", "--session",
        "--type=method_call",
        "--dest=org.onboard.Onboard",
        "/org/onboard/Onboard/Keyboard",
        "org.onboard.Onboard.Keyboard.ToggleVisible"])
}