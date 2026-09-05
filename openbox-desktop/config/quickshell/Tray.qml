import QtQuick
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray

// StatusNotifierItem tray (SNI over DBus, works fine on X11).
// Left click activates, right click opens the item's menu.
// Supports vertical (left bar) column and horizontal row.
Rectangle {
    id: root
    property bool vertical: false

    visible: SystemTray.items.values.length > 0
    implicitWidth: vertical ? Math.round(28 * Theme.barScale) : trayRow.implicitWidth + Math.round(14 * Theme.barScale)
    implicitHeight: vertical ? trayCol.implicitHeight + Math.round(14 * Theme.barScale) : Theme.moduleHeight
    radius: 8
    color: Qt.alpha(Theme.fg, 0.07)

    Row {
        id: trayRow
        visible: !root.vertical
        anchors.centerIn: parent
        spacing: 4

        Repeater {
            model: SystemTray.items

            MouseArea {
                id: trayItem
                required property SystemTrayItem modelData

                width: Math.round(20 * Theme.barScale)
                height: Theme.moduleHeight
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

                IconImage {
                    anchors.centerIn: parent
                    implicitSize: Math.round(16 * Theme.barScale)
                    source: trayItem.modelData.icon
                }

                QsMenuAnchor {
                    id: menuAnchor
                    menu: trayItem.modelData.menu
                    anchor.item: trayItem
                    anchor.rect.y: trayItem.height + 8
                }

                onClicked: m => {
                    if (m.button === Qt.LeftButton)
                        modelData.activate()
                    else if (m.button === Qt.MiddleButton)
                        modelData.secondaryActivate()
                    else if (modelData.hasMenu)
                        menuAnchor.open()
                }
            }
        }
    }

    Column {
        id: trayCol
        visible: root.vertical
        anchors.centerIn: parent
        spacing: 4

        Repeater {
            model: SystemTray.items

            MouseArea {
                id: trayItemV
                required property SystemTrayItem modelData

                width: Math.round(20 * Theme.barScale)
                height: Math.round(20 * Theme.barScale)
                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

                IconImage {
                    anchors.centerIn: parent
                    implicitSize: Math.round(16 * Theme.barScale)
                    source: trayItemV.modelData.icon
                }

                QsMenuAnchor {
                    id: menuAnchorV
                    menu: trayItemV.modelData.menu
                    anchor.item: trayItemV
                    anchor.rect.x: trayItemV.width + 8
                    anchor.rect.y: 0
                }

                onClicked: m => {
                    if (m.button === Qt.LeftButton)
                        modelData.activate()
                    else if (m.button === Qt.MiddleButton)
                        modelData.secondaryActivate()
                    else if (modelData.hasMenu)
                        menuAnchorV.open()
                }
            }
        }
    }
}
