pragma Singleton
import QtQuick
import Quickshell

// Color themes offered in the wallpaper picker. Each preset is a complete
// theme/colors.ini palette: selecting one writes those keys and Theme.qml
// recolors the bar, popups, and network app live. Add a theme by copying an
// entry and changing its name/colors.
Singleton {
    id: root

    readonly property var presets: [
        {
            name: "Redline",
            bg: "#222225", altbg: "#26262a", fg: "#e8e9ed",
            border: "#3f3f44", primary: "#d70a53",
            secondary: "#e5c07b", alert: "#ff6b9d", disabled: "#5c5c64"
        },
        {
            name: "Cobalt",
            bg: "#1d222b", altbg: "#222834", fg: "#e6ebf5",
            border: "#343d4e", primary: "#5c9dff",
            secondary: "#8be9fd", alert: "#ff7a9c", disabled: "#586274"
        },
        {
            name: "Mint",
            bg: "#1d2623", altbg: "#222d29", fg: "#e5f0ea",
            border: "#34443d", primary: "#4fd1a1",
            secondary: "#e5c07b", alert: "#ff8a80", disabled: "#56665f"
        },
        {
            name: "Violet",
            bg: "#241f2b", altbg: "#2a2433", fg: "#eee8f6",
            border: "#40364d", primary: "#b68cff",
            secondary: "#ff9ecb", alert: "#ff6b9d", disabled: "#655c73"
        },
        {
            name: "Ember",
            bg: "#2a211d", altbg: "#302722", fg: "#f3ebe5",
            border: "#493a32", primary: "#ff8a4c",
            secondary: "#e5c07b", alert: "#ff6b6b", disabled: "#6d5c53"
        },
        {
            name: "Ice",
            bg: "#1c242b", altbg: "#212b33", fg: "#e5f2f8",
            border: "#32434f", primary: "#7bdcff",
            secondary: "#b7c9ff", alert: "#ff6b9d", disabled: "#566773"
        },
        {
            name: "Sand",
            bg: "#27231d", altbg: "#2e2922", fg: "#f1ece3",
            border: "#453d32", primary: "#e0b35a",
            secondary: "#d9a441", alert: "#ff8a65", disabled: "#6a6154"
        },
        {
            name: "Blush",
            bg: "#2a2024", altbg: "#31252a", fg: "#f4e8ec",
            border: "#4a3540", primary: "#ff6b9d",
            secondary: "#ffb3c7", alert: "#ff8a80", disabled: "#6d5862"
        }
    ]
}
