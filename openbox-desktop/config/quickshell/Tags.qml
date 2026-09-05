import QtQuick

// 12 bspwm desktops: focused = wide accent pill, occupied = numbered cell,
// empty = small dot. Widths and colors animate on every report line.
// Supports vertical (left bar) and horizontal (top bar) orientations.
Item {
    id: root
    property bool vertical: false
    implicitWidth: vertical ? Math.round(22 * Theme.barScale) : tagRow.implicitWidth
    implicitHeight: vertical ? tagCol.implicitHeight : Math.round(22 * Theme.barScale)

    WheelHandler {
        onWheel: ev => Wm.cycleTag(ev.angleDelta.y > 0 ? -1 : 1)
    }

    Row {
        id: tagRow
        visible: !root.vertical
        spacing: 4
        anchors.verticalCenter: parent.verticalCenter

        Repeater {
            model: Wm.tagCount

            Rectangle {
                id: tag
                required property int index
                readonly property bool selected: (Wm.seltags & (1 << index)) !== 0
                readonly property bool occupied: (Wm.occtags & (1 << index)) !== 0
                readonly property bool urgent: (Wm.urgtags & (1 << index)) !== 0

                width: Math.round((selected ? 30 : occupied ? 22 : 12) * Theme.barScale)
                height: Math.round(22 * Theme.barScale)
                radius: Math.round(7 * Theme.barScale)
                anchors.verticalCenter: parent.verticalCenter
                color: urgent ? Theme.red
                     : selected ? Theme.selbg
                     : occupied ? Qt.alpha(Theme.fg, 0.08)
                     : "transparent"

                Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 180 } }

                SequentialAnimation on opacity {
                    running: tag.urgent
                    loops: Animation.Infinite
                    alwaysRunToEnd: true
                    NumberAnimation { to: 0.5; duration: 500; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 1.0; duration: 500; easing.type: Easing.InOutQuad }
                }

                Text {
                    anchors.centerIn: parent
                    visible: tag.occupied || tag.selected
                    text: tag.index + 1
                    color: tag.urgent ? Theme.bg
                         : tag.selected ? Theme.selfg
                         : Qt.alpha(Theme.fg, 0.85)
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.barScale)
                    font.bold: tag.selected
                    Behavior on color { ColorAnimation { duration: 180 } }
                }

                Rectangle {
                    visible: !tag.occupied && !tag.selected
                    anchors.centerIn: parent
                    width: Math.round(5 * Theme.barScale)
                    height: width
                    radius: width / 2
                    color: Qt.alpha(Theme.fg, 0.25)
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    onClicked: m => {
                        if (m.button === Qt.MiddleButton)
                            Wm.sendToTag(tag.index)
                        else
                            Wm.viewTag(tag.index)
                    }
                }
            }
        }
    }

    Column {
        id: tagCol
        visible: root.vertical
        spacing: 4
        anchors.horizontalCenter: parent.horizontalCenter

        Repeater {
            model: Wm.tagCount

            Rectangle {
                id: tagV
                required property int index
                readonly property bool selected: (Wm.seltags & (1 << index)) !== 0
                readonly property bool occupied: (Wm.occtags & (1 << index)) !== 0
                readonly property bool urgent: (Wm.urgtags & (1 << index)) !== 0

                width: Math.round(22 * Theme.barScale)
                height: Math.round((selected ? 30 : occupied ? 22 : 12) * Theme.barScale)
                radius: Math.round(7 * Theme.barScale)
                anchors.horizontalCenter: parent.horizontalCenter
                color: urgent ? Theme.red
                     : selected ? Theme.selbg
                     : occupied ? Qt.alpha(Theme.fg, 0.08)
                     : "transparent"

                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 180 } }

                SequentialAnimation on opacity {
                    running: tagV.urgent
                    loops: Animation.Infinite
                    alwaysRunToEnd: true
                    NumberAnimation { to: 0.5; duration: 500; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 1.0; duration: 500; easing.type: Easing.InOutQuad }
                }

                Text {
                    anchors.centerIn: parent
                    visible: tagV.occupied || tagV.selected
                    text: tagV.index + 1
                    color: tagV.urgent ? Theme.bg
                         : tagV.selected ? Theme.selfg
                         : Qt.alpha(Theme.fg, 0.85)
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.barScale)
                    font.bold: tagV.selected
                    Behavior on color { ColorAnimation { duration: 180 } }
                }

                Rectangle {
                    visible: !tagV.occupied && !tagV.selected
                    anchors.centerIn: parent
                    width: Math.round(5 * Theme.barScale)
                    height: width
                    radius: width / 2
                    color: Qt.alpha(Theme.fg, 0.25)
                }

                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                    onClicked: m => {
                        if (m.button === Qt.MiddleButton)
                            Wm.sendToTag(tagV.index)
                        else
                            Wm.viewTag(tagV.index)
                    }
                }
            }
        }
    }
}
