pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Minimal copy of the bar's Theme singleton: live palette from
// theme/colors.ini, so the network window follows the wallpaper theming.
Singleton {
    id: root

    // config root = parent of this app dir — derived, never hardcoded
    readonly property string configDir: {
        let sd = String(Quickshell.shellDir ?? "")
        if (sd.startsWith("file://"))
            sd = sd.slice(7)
        return sd.substring(0, sd.lastIndexOf("/"))
    }

    property color bg: "#222225"
    property color altbg: "#26262a"
    property color fg: "#e8e9ed"
    property color accent: "#d70a53"
    property color green: "#e5c07b"
    property color alert: "#ff6b9d"
    property color disabled: "#5c5c64"

    readonly property string fontFamily: "JetBrainsMono Nerd Font"

    FileView {
        path: root.configDir + "/theme/colors.ini"
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
        if (map["primary"]) accent = map["primary"]
        if (map["secondary"]) green = map["secondary"]
        if (map["alert"]) alert = map["alert"]
        if (map["disabled"]) disabled = map["disabled"]
    }
}
