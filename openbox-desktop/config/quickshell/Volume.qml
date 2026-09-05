import QtQuick
import Quickshell
import Quickshell.Services.Pipewire

// Default sink volume. Scroll to adjust, click to mute, right click for
// pavucontrol (floats via the bspwmrc rule).
BarModule {
    id: root

    PwObjectTracker {
        objects: [Pipewire.defaultAudioSink]
    }

    readonly property var audio: Pipewire.defaultAudioSink?.audio ?? null
    readonly property bool muted: audio?.muted ?? false
    readonly property int volume: audio ? Math.round(audio.volume * 100) : 0

    // flash the % briefly on any change (volume keys included)
    property bool flash: false
    onVolumeChanged: { flash = true; flashTimer.restart() }
    onMutedChanged: { flash = true; flashTimer.restart() }
    Timer {
        id: flashTimer
        interval: 1500
        onTriggered: root.flash = false
    }

    icon: muted ? "󰝟" : volume < 25 ? "󰕿" : volume < 65 ? "󰖀" : "󰕾"
    iconColor: muted ? Qt.alpha(Theme.fg, 0.45) : Theme.green
    label: hovered || flash ? (muted ? "--" : volume + "%") : ""

    onClicked: mouse => {
        if (mouse.button === Qt.RightButton)
            Quickshell.execDetached(["pavucontrol"])
        else if (audio)
            audio.muted = !audio.muted
    }
    onScrolled: dir => {
        if (audio) {
            audio.muted = false
            audio.volume = Math.max(0, Math.min(1, audio.volume + dir * 0.02))
        }
    }
}
