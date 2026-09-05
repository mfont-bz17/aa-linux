import QtQuick

// Debian swirl — the command center, no extra buttons needed:
//   left: app launcher · right: wallpaper picker · middle: random wallpaper
// Both wallpaper paths re-theme the desktop from the image's palette.
// FiraCode NF carries the Font Logos glyph; JetBrainsMono NF here doesn't.
BarModule {
    id: root

    icon: ""  // Debian swirl (Font Logos)
    iconFont: "FiraCode Nerd Font"
    iconColor: Theme.accent
    onClicked: mouse => {
        picker.toggle()
    }

    WallpaperPicker {
        id: picker
        anchorItem: root
    }
}
