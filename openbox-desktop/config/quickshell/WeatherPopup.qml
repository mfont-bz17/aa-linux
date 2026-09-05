import QtQuick

import Quickshell.Io
// Three-day forecast under the weather indicator — the calendar idiom:
// click the number, get the picture. Data comes from the same wttr.in
// fetch the bar module already makes; no extra requests.
Popout {
    id: root

    property string condition: ""
    property string feels: ""
    property string wind: ""
    property string place: ""
    property var days: []   // {label, glyph, hi, lo, rain}

    cardWidth: 300
    cardHeight: 168

    // scriptable: qs -p ~/.config/bspwm/quickshell ipc call weather toggle
    IpcHandler {
        target: "weather"
        function toggle(): void { root.visible = !root.visible }
    }

    // where this forecast is for — also the tell when a VPN exit node is
    // fooling wttr.in's IP geolocation
    Text {
        id: placeLine
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        visible: root.place !== ""
        text: "󰍎 " + root.place
        color: Qt.alpha(Theme.fg, 0.5)
        font.family: Theme.fontFamily
        font.pixelSize: 10
        elide: Text.ElideRight
    }

    // current condition · feels like · wind
    Text {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: placeLine.visible ? placeLine.bottom : parent.top
        anchors.topMargin: placeLine.visible ? 4 : 0
        text: root.condition
            + (root.feels !== "" ? "  ·  feels " + root.feels + "°" : "")
            + (root.wind !== "" ? "  ·  󰖝 " + root.wind : "")
        color: Theme.fg
        font.family: Theme.fontFamily
        font.pixelSize: 12
        font.bold: true
        elide: Text.ElideRight
    }

    Row {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.topMargin: 12
        anchors.bottom: parent.bottom

        Repeater {
            model: root.days

            Column {
                id: day
                required property var modelData
                width: parent.width / Math.max(root.days.length, 1)
                spacing: 5

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: day.modelData.label
                    color: Qt.alpha(Theme.fg, 0.55)
                    font.family: Theme.fontFamily
                    font.pixelSize: 11
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: day.modelData.glyph
                    color: Theme.yellow
                    font.family: Theme.fontFamily
                    font.pixelSize: 22
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: day.modelData.hi + "° / " + day.modelData.lo + "°"
                    color: Theme.fg
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: day.modelData.rain >= 30
                    text: "󰖌 " + day.modelData.rain + "%"
                    color: Theme.cyan
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                }
            }
        }
    }
}
