import QtQuick

// Opens the existing rofi power menu script.
BarModule {
    icon: "⏻"
    iconColor: Theme.red
    onClicked: Wm.openPowerMenu()
}
