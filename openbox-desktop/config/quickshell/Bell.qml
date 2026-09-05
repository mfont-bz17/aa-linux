import QtQuick

// Notifications: quiet bell while dunst is live, red bell-off while paused
// (do-not-disturb). Click toggles DND; right click opens recent history.
BarModule {
    id: root

    icon: Sys.dndOn ? "󰂛" : "󰂚"
    iconColor: Sys.dndOn ? Theme.red : Qt.alpha(Theme.fg, 0.45)

    onClicked: mouse => {
        if (mouse.button === Qt.RightButton)
            history.visible = !history.visible
        else
            Sys.toggleDnd()
    }

    NotifyPopup {
        id: history
        anchorItem: root
    }
}
