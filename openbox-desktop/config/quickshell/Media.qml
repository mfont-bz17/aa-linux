import QtQuick
import Quickshell.Services.Mpris

// Now-playing (MPRIS). Hidden when nothing is playing. Click toggles
// play/pause, scroll skips tracks. Elapsed/total timestamps plus a
// progress underline when the track reports a length (streams don't).
BarModule {
    id: root
    property bool vertical: false

    readonly property var player: Mpris.players.values.length > 0 ? Mpris.players.values[0] : null
    readonly property bool playing: player !== null
        && player.playbackState === MprisPlaybackState.Playing

    visible: player !== null && player.playbackState !== MprisPlaybackState.Stopped

    // MPRIS doesn't push position updates — tick it while playing
    property real pos: 0
    readonly property real len: player?.length ?? 0
    readonly property bool timed: len > 0 && isFinite(len)

    Timer {
        running: root.visible && root.playing
        interval: 1000
        repeat: true
        triggeredOnStart: true
        onTriggered: root.pos = root.player?.position ?? 0
    }
    // re-read immediately on track change / seek while paused
    Connections {
        target: root.player
        function onTrackTitleChanged() { root.pos = root.player?.position ?? 0 }
        function onPositionChanged() { root.pos = root.player?.position ?? 0 }
    }

    function fmt(s) {
        s = Math.max(0, Math.round(s))
        const m = Math.floor(s / 60), r = s % 60
        return (m >= 60 ? Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0")
                        : m) + ":" + String(r).padStart(2, "0")
    }

    icon: playing ?  "󰏤": "󰐊" 
    iconColor: Theme.magenta
    label: {
        if (root.vertical)
            return ""
        if (!player)
            return ""
        const artist = player.trackArtists && player.trackArtists.length > 0
            ? player.trackArtists.join(", ") : ""
        const t = artist !== "" ? artist + " — " + player.trackTitle : (player.trackTitle ?? "")
        return t.length > 40 ? t.slice(0, 38) + "…" : t
    }
    progress: timed ? Math.min(pos / len, 1) : -1

    Text {
        visible: root.timed && !root.vertical
        anchors.verticalCenter: parent.verticalCenter
        text: root.fmt(root.pos) + " / " + root.fmt(root.len)
        color: Qt.alpha(Theme.fg, 0.6)
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(9, Theme.fontSize - 2)
    }

    onClicked: {
        if (player && player.canTogglePlaying)
            player.togglePlaying()
    }
    onScrolled: dir => {
        if (!player)
            return
        if (dir > 0 && player.canGoPrevious)
            player.previous()
        else if (dir < 0 && player.canGoNext)
            player.next()
    }
}
