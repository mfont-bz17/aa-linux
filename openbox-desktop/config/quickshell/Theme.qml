pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Live palette sourced from the bspwm theme switcher. The switcher rewrites
// polybar/colors.ini (and colors.sh) in place on every switch, so watching
// that file re-colors the bar with no restart — polybar itself can be
// retired without breaking this. Defaults are github_dark placeholders.
//
// The polybar palette is smaller than dwm's xresources+ANSI set, so the
// semantic names below collapse onto it: red→alert, yellow→primary,
// blue/green/cyan/magenta→secondary. Cohesive by construction.
Singleton {
    id: root

    // config root = parent of the running quickshell dir, derived rather
    // than hardcoded so vendored copies (openbox etc.) need no path edits
    readonly property string configDir: {
        let sd = String(Quickshell.shellDir ?? "")
        if (sd.startsWith("file://"))
            sd = sd.slice(7)
        return sd.substring(0, sd.lastIndexOf("/"))
    }

    // bar size and element scale, persisted to plain files (like
    // weather-location) so the tweaks sliders survive restarts.
    // barHeight is kept for migration/back-compat; effective geometry for
    // the left-vertical bar is barWidth / effectiveBarWidth.
    property int barHeight: 42
    property int barWidth: 56
    property real barUserScale: 1.0

    // state files attempted (present or not); bars gate their first
    // map on this to appear once at final size (openbox re-clamps docks
    // on resize). The timer failsafe guarantees the bar always maps.
    property int _barStateLoads: 0
    readonly property bool barStateReady: _barStateLoads >= 3
    Timer {
        running: !root.barStateReady
        interval: 1000
        onTriggered: root._barStateLoads = 3
    }

    property color bg: "#0d1117"
    property color altbg: "#161b22"
    property color fg: "#c9d1d9"
    property color border: "#30363d"
    property color primary: "#58a6ff"
    property color secondary: "#8b949e"
    property color alert: "#f85149"
    property color disabled: "#484f58"

    readonly property color accent: primary
    readonly property color selbg: primary
    readonly property color selfg: bg
    readonly property color red: alert
    readonly property color yellow: primary
    readonly property color blue: secondary
    readonly property color green: secondary
    readonly property color cyan: secondary
    readonly property color magenta: secondary

    readonly property string fontFamily: "JetBrainsMono Nerd Font"

    // In-bar elements follow the scale slider; popups stay fixed.
    // barHeight/barWidth are floors: the window grows when scaled modules
    // outgrow them. Vertical bar uses effectiveBarWidth; horizontal
    // fallback would use effectiveBarHeight.
    readonly property real barScale: barUserScale
    readonly property int fontSize: Math.round(13 * barScale)
    readonly property int iconSize: Math.round(15 * barScale)
    readonly property int moduleHeight: Math.round(26 * barScale)
    readonly property int effectiveBarHeight: Math.max(barHeight, moduleHeight + 12)
    readonly property int effectiveBarWidth: Math.max(barWidth, moduleHeight + 16)

    FileView {
        path: root.configDir + "/bar-height"
        watchChanges: true
        onFileChanged: reload()
        onLoadFailed: root._barStateLoads++
        onLoaded: {
            root._barStateLoads++
            const v = parseInt(text())
            if (!isNaN(v))
                root.barHeight = Math.min(Math.max(v, 32), 80)
        }
    }

    FileView {
        path: root.configDir + "/bar-width"
        watchChanges: true
        onFileChanged: reload()
        onLoadFailed: root._barStateLoads++
        onLoaded: {
            root._barStateLoads++
            const v = parseInt(text())
            if (!isNaN(v))
                root.barWidth = Math.min(Math.max(v, 40), 120)
        }
    }

    FileView {
        path: root.configDir + "/bar-scale"
        watchChanges: true
        onFileChanged: reload()
        onLoadFailed: root._barStateLoads++
        onLoaded: {
            root._barStateLoads++
            const v = parseFloat(text())
            if (!isNaN(v))
                root.barUserScale = Math.min(Math.max(v, 0.7), 2.0)
        }
    }

    FileView {
        path: root.configDir + "/polybar/colors.ini"
        watchChanges: true
        onFileChanged: reload()
        onLoaded: root.parseIni(text())
    }

    function parseIni(t) {
        const map = {}
        for (const line of t.split("\n")) {
            const m = line.match(/^\s*([A-Za-z-]+)\s*=\s*(#[0-9a-fA-F]{3,8})/)
            if (m)
                map[m[1]] = m[2]
        }
        if (map["background"]) bg = map["background"]
        if (map["background-alt"]) altbg = map["background-alt"]
        if (map["foreground"]) fg = map["foreground"]
        if (map["border"]) border = map["border"]
        if (map["primary"]) primary = map["primary"]
        if (map["secondary"]) secondary = map["secondary"]
        if (map["alert"]) alert = map["alert"]
        if (map["disabled"]) disabled = map["disabled"]
    }
}
