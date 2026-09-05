import QtQuick
import Quickshell

// Date + 12-hour time (the slstatus formats), with a calendar on click.
// Vertical (left bar) uses a compact two-line layout to fit narrow width.
BarModule {
    id: root
    property bool vertical: false

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }

    // horizontal: "Tue Sep 1  3:30 PM" ; vertical: column draws both lines
    label: root.vertical ? "" : Qt.formatDateTime(clock.date, "ddd MMM d") + "  " + Qt.formatDateTime(clock.date, "h:mm AP")

    // vertical: time stacked vertically (hour above minute above AM/PM)
    // and date below – all centered to fit narrow bar
    Column {
        visible: root.vertical
        anchors.centerIn: parent
        spacing: 3

        // time vertical stack
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "h")
                color: Theme.fg
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "mm")
                color: Theme.fg
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "AP")
                color: Qt.alpha(Theme.fg, 0.7)
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(8, Theme.fontSize - 5)
                horizontalAlignment: Text.AlignHCenter
            }
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.round(16 * Theme.barScale)
            height: 1
            color: Qt.alpha(Theme.fg, 0.15)
            visible: true
        }

        // date stacked vertically for narrow width
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 0
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "ddd")
                color: Qt.alpha(Theme.fg, 0.6)
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(9, Theme.fontSize - 2)
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "MMM")
                color: Qt.alpha(Theme.fg, 0.5)
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(8, Theme.fontSize - 4)
                horizontalAlignment: Text.AlignHCenter
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(clock.date, "d")
                color: Qt.alpha(Theme.fg, 0.6)
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(10, Theme.fontSize - 1)
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
    // widen height when vertical to fit stacked time+date
    implicitHeight: root.vertical ? Math.round(112 * Theme.barScale) : Theme.moduleHeight

    onClicked: calendar.visible = !calendar.visible

    CalendarPopup {
        id: calendar
        anchorItem: root
    }
}
