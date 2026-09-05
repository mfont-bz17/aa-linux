import QtQuick
import Quickshell

// Shared shell for every bar popup: a fullscreen transparent catcher window
// with the styled card anchored under its bar item. Clicking anywhere
// outside the card closes it; Escape too (when X grants the popup key
// focus). All popups use this, so chrome and behavior stay identical.
// Note: spans the primary screen — revisit offsets if a second monitor
// ever joins.
PopupWindow {
    id: root

    property Item anchorItem
    property real cardWidth: 300
    property real cardHeight: 300
    readonly property real cardPadding: 14
    // right-edge panel mode (control center) instead of centered-under-anchor
    property bool alignRight: false

    default property alias content: inner.data

    visible: false
    color: "transparent"

    anchor.item: anchorItem
    // stretch the window over the whole screen so outside clicks land on it
    anchor.rect.x: anchorItem ? -anchorItem.mapToGlobal(0, 0).x : 0
    anchor.rect.y: anchorItem ? -anchorItem.mapToGlobal(0, 0).y : 0
    implicitWidth: Quickshell.screens.length ? Quickshell.screens[0].width : 1920
    implicitHeight: Quickshell.screens.length ? Quickshell.screens[0].height : 1080

    // anchor's global position, captured at open time — mapToGlobal in a
    // static binding evaluates before the item is mapped and returns 0
    property real ax: 0
    property real ay: 0

    onVisibleChanged: {
        if (visible && anchorItem) {
            const p = anchorItem.mapToGlobal(0, 0)
            ax = p.x
            ay = p.y
            inner.forceActiveFocus()
            enterAnim.restart()
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: root.visible = false
    }

    Rectangle {
        id: card

        // left-vertical bar: card appears to the right of the anchor,
        // vertically centered on it. alignRight (control center) pins to
        // the far right edge regardless.
        x: root.alignRight ? root.width - width - 8
         : root.ax + (root.anchorItem?.width ?? 0) + 12
        y: root.alignRight ? 8
         : Math.min(Math.max(root.ay + (root.anchorItem?.height ?? 0) / 2 - height / 2, 8),
                    root.height - height - 8)

        transform: Translate { id: slide; x: 0 }

        ParallelAnimation {
            id: enterAnim
            NumberAnimation { target: slide; property: "x"; from: -10; to: 0
                              duration: 160; easing.type: Easing.OutCubic }
            NumberAnimation { target: card; property: "opacity"; from: 0; to: 1
                              duration: 160 }
        }
        width: root.cardWidth
        height: root.cardHeight
        radius: 12
        color: Theme.bg
        border.width: 1
        border.color: Qt.alpha(Theme.accent, 0.4)

        Behavior on color { ColorAnimation { duration: 250 } }

        // swallow card clicks so they don't fall through to the catcher
        MouseArea { anchors.fill: parent }

        Item {
            id: inner
            anchors.fill: parent
            anchors.margins: root.cardPadding
            focus: true
            Keys.onEscapePressed: root.visible = false
        }
    }
}
