import QtQuick
import Quickshell.Io

// SVG aa-linux mark: the rounded A and cursor, without Tux. The SVG is
// rasterized at 256px for crisp edges at every bar scale, and its color
// tokens are replaced from the live Theme palette on every change.
Item {
    id: root

    property color markColor: Theme.accent
    property color cursorColor: Theme.fg

    implicitWidth: Math.round(Theme.iconSize * 1.2)
    implicitHeight: implicitWidth

    property string _markup: ""

    function hex(c) {
        return "#" + String(c).slice(-6)
    }

    FileView {
        id: svgFile
        path: Qt.resolvedUrl("assets/aa-linux-mark.svg")
        watchChanges: true
        onLoaded: root._markup = text()
        onFileChanged: reload()
    }

    Image {
        anchors.fill: parent
        sourceSize.width: 256
        sourceSize.height: 256
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        source: root._markup === "" ? "" : "data:image/svg+xml;utf8,"
            + encodeURIComponent(root._markup
                .replace(/\{\{MARK\}\}/g, root.hex(root.markColor))
                .replace(/\{\{CURSOR\}\}/g, root.hex(root.cursorColor)))
    }
}
