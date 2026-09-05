import QtQuick
import Quickshell
import Quickshell.Io

// Bar tweaks popup, opened by right-clicking an empty stretch of the
// bar. Sliders apply live and persist to the state files (bar-width
// for the left-vertical bar, bar-scale) watched by Theme.qml.
// bar-height is kept for backward compat but not shown.
Popout {
    id: root

    cardWidth: 300
    cardHeight: col.implicitHeight + 2 * cardPadding

    // scriptable open/close: qs -p ~/.config/openbox/quickshell ipc call tweaks toggle
    IpcHandler {
        target: "tweaks"
        function toggle(): void { root.visible = !root.visible }
    }

    function persistFile(name, v) {
        Quickshell.execDetached(["sh", "-c",
            "printf '%s\\n' " + v + " > '" + Theme.configDir + "/" + name + "'"])
    }

    Item {
        anchors.fill: parent

        Column {
            id: col
            anchors.fill: parent
            spacing: 6

            Text {
                text: "Bar"
                color: Theme.accent
                font.family: Theme.fontFamily
                font.pixelSize: 12
                font.bold: true
            }

            TweakSlider {
                label: "bar width"
                from: 40; to: 100
                value: Theme.barWidth
                suffix: " px"
                applyFn: v => Theme.barWidth = v
                persistFn: v => root.persistFile("bar-width", v)
            }
            TweakSlider {
                label: "element scale"
                from: 0.7; to: 2.0
                value: Theme.barUserScale
                isInt: false
                suffix: "×"
                applyFn: v => Theme.barUserScale = v
                persistFn: v => root.persistFile("bar-scale", v)
            }
        }
    }
}
