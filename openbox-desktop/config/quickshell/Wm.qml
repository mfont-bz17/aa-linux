pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// EWMH state + control — openbox backend, works on any EWMH-compliant WM.
// Desktop state streams from an xprop spy on the root window; occupancy is
// recomputed from the client list (debounced). Actions go through xdotool.
// The focused window title comes from the same two-stage xprop spy as the
// bspwm backend.
Singleton {
    id: root

    property int seltags: 1
    property int occtags: 0
    property int urgtags: 0     // urgency not tracked on EWMH yet
    property int tagCount: 4
    property string title: ""
    property string activeWinId: ""

    Process {
        command: ["xprop", "-spy", "-root",
                  "_NET_CURRENT_DESKTOP", "_NET_NUMBER_OF_DESKTOPS", "_NET_CLIENT_LIST"]
        running: true
        stdout: SplitParser {
            onRead: line => {
                if (line.indexOf("_NET_CURRENT_DESKTOP") === 0) {
                    const m = line.match(/= (\d+)/)
                    if (m)
                        root.seltags = 1 << parseInt(m[1])
                } else if (line.indexOf("_NET_NUMBER_OF_DESKTOPS") === 0) {
                    const m = line.match(/= (\d+)/)
                    if (m)
                        root.tagCount = parseInt(m[1])
                }
                // any of these events can change occupancy (open/close/move)
                occRefresh.restart()
            }
        }
    }

    Timer {
        id: occRefresh
        interval: 150
        onTriggered: {
            occProc.running = false
            occProc.running = true
        }
    }

    property int _occ: 0
    Process {
        id: occProc
        command: ["sh", "-c",
            "for w in $(xprop -root _NET_CLIENT_LIST 2>/dev/null | grep -oE '0x[0-9a-f]+'); do " +
            "xprop -id $w _NET_WM_DESKTOP 2>/dev/null | grep -oE '[0-9]+$'; done"]
        stdout: SplitParser {
            onRead: line => {
                const d = parseInt(line)
                if (!isNaN(d) && d >= 0 && d < 31) // 0xFFFFFFFF = sticky, skip
                    root._occ |= 1 << d
            }
        }
        onRunningChanged: {
            if (running) root._occ = 0
            else root.occtags = root._occ
        }
    }

    // --- focused window title ---

    Process {
        command: ["xprop", "-spy", "-root", "_NET_ACTIVE_WINDOW"]
        running: true
        stdout: SplitParser {
            onRead: line => {
                const m = line.match(/window id # (0x[0-9a-fA-F]+)/)
                const id = m ? m[1] : ""
                if (id !== root.activeWinId) {
                    root.activeWinId = id
                    titleSpy.running = false
                    if (id !== "")
                        titleSpy.running = true
                    else
                        root.title = ""
                }
            }
        }
    }

    Process {
        id: titleSpy
        command: ["xprop", "-spy", "-id", root.activeWinId, "_NET_WM_NAME"]
        stdout: SplitParser {
            onRead: line => {
                const m = line.match(/= "([\s\S]*)"$/)
                if (m)
                    root.title = m[1].replace(/\\"/g, '"').replace(/\\\\/g, "\\")
            }
        }
    }

    // --- actions ---

    function viewTag(i) { Quickshell.execDetached(["xdotool", "set_desktop", String(i)]) }
    function toggleViewTag(i) { viewTag(i) }
    function sendToTag(i) {
        Quickshell.execDetached(["xdotool", "getactivewindow", "set_desktop_for_window", String(i)])
    }
    function cycleTag(dir) {
        Quickshell.execDetached(["xdotool", "set_desktop", "--relative", "--", String(dir)])
    }

    function openLauncher() {
        Quickshell.execDetached(["rofi", "-show", "drun", "-modi", "drun",
            "-line-padding", "4", "-hide-scrollbar", "-show-icons",
            "-theme", Theme.configDir + "/rofi/config.rasi"])
    }
    function openPowerMenu() {
        Quickshell.execDetached([Theme.configDir + "/scripts/power"])
    }
}
