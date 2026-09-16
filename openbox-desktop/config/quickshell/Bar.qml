import QtQuick
import Quickshell

// Vertical left bar, effectiveBarWidth px wide. Openbox honors the strut
// (no padding sync needed) but re-clamps docks into rc.xml <margins> on
// map and on resize — so re-run `scripts/bar place` (idempotent) each
// time the width settles.
PanelWindow {
    id: root

    property var modelData
    screen: modelData

    anchors {
        top: true
        left: true
        bottom: true
    }
    implicitWidth: Theme.effectiveBarWidth
    color: "transparent"
    // map once, at final size — see Theme.barStateReady
    visible: Theme.barStateReady

    onImplicitWidthChanged: placeTimer.restart()
    Timer {
        id: placeTimer
        interval: 150
        onTriggered: Quickshell.execDetached(
            [Theme.configDir + "/scripts/bar", "place", "fast"])
    }

    Rectangle {
        id: panel
        anchors.fill: parent
        anchors.topMargin: 8
        anchors.leftMargin: 8
        anchors.rightMargin: 2
        anchors.bottomMargin: 8

        radius: 10
        color: Qt.alpha(Theme.bg, 0.94)
        border.width: 1
        border.color: Qt.alpha(Theme.accent, 0.35)

        Behavior on color { ColorAnimation { duration: 400 } }
        Behavior on border.color { ColorAnimation { duration: 400 } }

        // top stack — launcher, tags, tray
        Column {
            id: topCluster
            anchors.top: parent.top
            anchors.topMargin: 8
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 8
            spacing: 6

            Launcher { width: parent.width }
            Clock { vertical: true; width: parent.width }
            Tags { vertical: true; anchors.horizontalCenter: parent.horizontalCenter; width: parent.width }
            //Tray { vertical: true; width: parent.width }
            //CapsLock { width: parent.width }
        }

        // bottom stack — system modules anchored to bottom
        Column {
            id: bottomCluster
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 8
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width - 8
            spacing: 4

            Onboard { width: parent.width }
            Media { vertical: true; width: parent.width }
            //Weather { vertical: true; width: parent.width }
            //Metrics { vertical: true; width: parent.width }
            //Volume { width: parent.width }
            //Network { width: parent.width }
            //Bell { width: parent.width }
            //PowerButton { width: parent.width }
        }
    }
}
