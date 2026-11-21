import QtQuick

// aa-linux mark — the command center, no extra buttons needed:
//   left: app launcher · right: wallpaper picker · middle: random wallpaper
// Both wallpaper paths re-theme the desktop from the image's palette.
BarModule {
    id: root

    onClicked: mouse => {
        picker.toggle()
    }

    // SVG mark recolors from the live Theme palette (no raster asset).
    AaMark {
        anchors.verticalCenter: parent.verticalCenter
    }

    WallpaperPicker {
        id: picker
        anchorItem: root
    }
}
