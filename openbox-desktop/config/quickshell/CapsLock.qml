import QtQuick

// Caps-lock warning, ported from the polybar setup: hidden until caps is on,
// then an alert-colored pill.
BarModule {
    visible: Sys.capsOn
    icon: "󰘲"
    iconColor: Theme.bg
    label: "Caps"
    labelColor: Theme.bg
    color: Theme.red
    interactive: false
}
