import QtQuick

// Base pill for bar modules: optional nerd-font icon + label, hover feedback,
// click/scroll signals. Extra content can be added as children.
Rectangle {
    id: root

    property string icon: ""
    property color iconColor: Theme.accent
    // some glyphs (e.g. Font Logos ) are missing from JetBrainsMono NF here
    property string iconFont: Theme.fontFamily
    property string label: ""
    property color labelColor: Theme.fg
    property bool interactive: true
    readonly property bool hovered: mouse.containsMouse

    // progress underline along the pill bottom: 0..1 shows it, negative hides
    property real progress: -1

    signal clicked(var mouse)
    signal scrolled(int dir)

    default property alias extraContent: row.data

    implicitHeight: Theme.moduleHeight
    implicitWidth: row.implicitWidth + Math.round(18 * Theme.barScale)
    radius: 8
    color: mouse.containsMouse && interactive ? Qt.alpha(Theme.fg, 0.14) : Qt.alpha(Theme.fg, 0.07)
    // tactile press feedback — slow-starting apps otherwise make a click
    // feel like it didn't register
    scale: mouse.pressed && interactive ? 0.9 : 1

    Behavior on color { ColorAnimation { duration: 150 } }
    Behavior on scale { NumberAnimation { duration: 80; easing.type: Easing.OutQuad } }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: Math.round(7 * Theme.barScale)

        Text {
            visible: root.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.icon
            color: root.iconColor
            font.family: root.iconFont
            font.pixelSize: Theme.iconSize
            Behavior on color { ColorAnimation { duration: 250 } }
        }

        Text {
            visible: root.label !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: root.labelColor
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            Behavior on color { ColorAnimation { duration: 250 } }
        }
    }

    Rectangle {
        visible: root.progress >= 0
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.radius
        anchors.bottomMargin: 2
        height: 2
        radius: 1
        width: Math.min(Math.max(root.progress, 0), 1) * (parent.width - 2 * root.radius)
        color: Theme.accent
        opacity: 0.9
        Behavior on width { NumberAnimation { duration: 300 } }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        onClicked: m => root.clicked(m)
        onWheel: w => root.scrolled(w.angleDelta.y > 0 ? 1 : -1)
    }
}
