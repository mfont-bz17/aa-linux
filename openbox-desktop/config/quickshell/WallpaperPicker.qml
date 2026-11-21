import QtQuick
import Quickshell
import Quickshell.Io

// Wallpaper picker popup: a thumbnail grid of ~/.config/bspwm/wallpaper,
// plus a color-theme strip. Picking a wallpaper extracts a palette from the
// image right here (hidden Image → Canvas histogram → HSL-derived semantic
// colors) and hands wallpaper + palette to scripts/set-wallpaper. Picking a
// theme writes theme/colors.ini, which Theme.qml watches live.
// No pywal/wallust needed — quickshell is the color engine.
Popout {
    id: root

    cardWidth: 176 * 3 + 2 * cardPadding
    cardHeight: 4 * 103 + 64 + 8 + 2 * cardPadding

    property var wallpapers: []
    property string applyingPath: ""
    property bool randomPending: false

    // custom accent picker
    property bool customOpen: false
    property real customHue: 340
    property real customSat: 70
    property real customVal: 80
    readonly property string customHex: hsvToHex(customHue, customSat / 100,
                                                 customVal / 100)

    // The active preset is derived from the live palette, so an externally
    // edited colors.ini simply shows as "Custom" instead of lying.
    readonly property string currentTheme: {
        const p = String(Theme.primary).toLowerCase()
        for (const t of ColorThemes.presets)
            if (t.primary.toLowerCase() === p)
                return t.name
        return "Custom"
    }

    FileView {
        id: paletteFile
        path: Theme.configDir + "/theme/colors.ini"
    }

    function applyTheme(theme) {
        paletteFile.setText([
            "; aa-linux desktop palette",
            "; Written by quickshell/WallpaperPicker.qml; read live by Theme.qml.",
            "background = " + theme.bg,
            "background-alt = " + theme.altbg,
            "foreground = " + theme.fg,
            "border = " + theme.border,
            "primary = " + theme.primary,
            "secondary = " + theme.secondary,
            "alert = " + theme.alert,
            "disabled = " + theme.disabled
        ].join("\n") + "\n")
    }

    function hexOf(c) {
        return "#" + String(c).slice(-6)
    }

    function openCustom() {
        const hex = hexOf(Theme.primary)
        const hsv = rgbToHsv(
            parseInt(hex.slice(1, 3), 16) / 255,
            parseInt(hex.slice(3, 5), 16) / 255,
            parseInt(hex.slice(5, 7), 16) / 255)
        customHue = Math.round(hsv[0])
        customSat = Math.round(hsv[1] * 100)
        customVal = Math.round(hsv[2] * 100)
        customOpen = true
    }

    function toggleCustom() {
        if (customOpen)
            customOpen = false
        else
            openCustom()
    }

    function applyCustom() {
        const h = customHue
        const s = customSat / 100
        const v = customVal / 100
        const primary = hsvToHex(h, s, v)

        // Keep the current surfaces and derive a coherent pair of accents.
        applyTheme({
            name: "Custom",
            bg: hexOf(Theme.bg),
            altbg: hexOf(Theme.altbg),
            fg: hexOf(Theme.fg),
            border: hexOf(Theme.border),
            primary: primary,
            secondary: hsvToHex((h + 160) % 360,
                Math.min(Math.max(s * 0.35, 0.15), 0.55),
                Math.min(v + 0.12, 1.0)),
            alert: hsvToHex(345,
                Math.min(Math.max(s * 0.9, 0.45), 0.9),
                Math.min(Math.max(v, 0.75), 0.98)),
            disabled: hexOf(Theme.disabled)
        })
        customOpen = false
    }

    // re-scan the wallpaper dir on every open, so new files just show up
    onVisibleChanged: {
        if (visible)
            lister.running = true
        else
            customOpen = false
    }

    function toggle() { visible = !visible }

    // Keep wallpapers in the same order as the theme swatches. Files that
    // don't match a preset (or the Redline base) sort after the presets.
    function themeRank(path) {
        const base = String(path).split("/").pop()
            .replace(/\.(png|jpe?g)$/i, "").toLowerCase()
        const name = base.startsWith("aa-linux-")
            ? base.slice("aa-linux-".length) : base
        for (let i = 0; i < ColorThemes.presets.length; i++)
            if (ColorThemes.presets[i].name.toLowerCase() === name)
                return i
        return ColorThemes.presets.length
    }

    function applyRandom() {
        randomPending = true
        lister.running = true
    }

    function apply(path) {
        applyingPath = path
        if (!visible)
            visible = true // canvas only renders inside a visible window
        canvas.loadImage("file://" + path)
    }

    // sxhkd entry point: qs -p ~/.config/bspwm/quickshell ipc call wallpapers toggle
    IpcHandler {
        target: "wallpapers"
        function toggle(): void { root.toggle() }
        function random(): void { root.applyRandom() }
        function set(path: string): void { root.apply(path) }
    }

    property var _found: []
    Process {
        id: lister
        // no SVGs: Qt's loader chokes on ones with external references
        command: ["sh", "-c",
            "find \"" + Theme.configDir + "/wallpaper\" -maxdepth 1 -type f " +
            "\\( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \\) | sort"]
        stdout: SplitParser {
            onRead: line => { if (line.trim() !== "") root._found.push(line.trim()) }
        }
        onRunningChanged: {
            if (running) {
                root._found = []
            } else {
                root.wallpapers = root._found.slice().sort((a, b) => {
                    const ra = root.themeRank(a), rb = root.themeRank(b)
                    return ra !== rb ? ra - rb : a.localeCompare(b)
                })
                if (root.randomPending) {
                    root.randomPending = false
                    if (root.wallpapers.length > 0)
                        root.apply(root.wallpapers[
                            Math.floor(Math.random() * root.wallpapers.length)])
                }
            }
        }
    }

    Item {
        anchors.fill: parent

        // extraction surface — loadImage decodes the wallpaper full-size,
        // drawImage-by-url scales it down here, getImageData samples it;
        // sits behind the opaque grid (chrome comes from Popout)
        Canvas {
            id: canvas
            x: 0; y: 0
            width: 96
            height: 54

            onImageLoaded: {
                const url = "file://" + root.applyingPath
                if (root.applyingPath !== "" && isImageError(url))
                    root.applyingPath = ""
                else
                    requestPaint()
            }

            onPaint: {
                if (root.applyingPath === "")
                    return
                const url = "file://" + root.applyingPath
                if (!isImageLoaded(url))
                    return
                const ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.drawImage(url, 0, 0, width, height)
                const data = ctx.getImageData(0, 0, width, height).data
                unloadImage(url) // free the full-res decode (~20MB)
                root.finish(data)
            }
        }

        Column {
            anchors.fill: parent
            spacing: 8

            // color-theme strip: the active preset, then one swatch per preset
            Item {
                id: themeBlock
                width: parent.width
                height: 64

                Text {
                    id: themeLabel
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: "Color theme"
                    color: Theme.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: 12
                    font.bold: true
                }

                Text {
                    anchors.right: parent.right
                    anchors.baseline: themeLabel.baseline
                    text: root.currentTheme
                    color: Qt.alpha(Theme.fg, 0.55)
                    font.family: Theme.fontFamily
                    font.pixelSize: 10
                }

                Row {
                    anchors.left: parent.left
                    anchors.top: themeLabel.bottom
                    anchors.topMargin: 6
                    spacing: 4

                    Repeater {
                        model: ColorThemes.presets

                        Item {
                            id: swatchCell
                            required property var modelData
                            readonly property bool selected: root.currentTheme === modelData.name
                            width: 55
                            height: 42

                            Rectangle {
                                id: swatch
                                anchors.top: parent.top
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: parent.width
                                height: 26
                                radius: 6
                                // one theme = one swatch; the preset's other
                                // colors still drive secondary/alert elsewhere
                                color: swatchCell.modelData.primary
                                border.width: swatchCell.selected ? 2 : 1
                                border.color: swatchCell.selected
                                    ? Theme.fg
                                    : swatchMouse.containsMouse
                                        ? Qt.alpha(Theme.fg, 0.55)
                                        : Qt.alpha(Theme.fg, 0.16)
                                Behavior on border.color { ColorAnimation { duration: 120 } }
                            }

                            Text {
                                anchors.top: swatch.bottom
                                anchors.topMargin: 3
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: swatchCell.modelData.name
                                color: swatchCell.selected || swatchMouse.containsMouse
                                    ? Theme.accent
                                    : Qt.alpha(Theme.fg, 0.55)
                                font.family: Theme.fontFamily
                                font.pixelSize: 9
                            }

                            MouseArea {
                                id: swatchMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: root.applyTheme(swatchCell.modelData)
                            }
                        }
                    }

                    // custom accent swatch opens the inline picker
                    Item {
                        id: customCell
                        readonly property bool selected: root.currentTheme === "Custom"
                        width: 55
                        height: 42

                        Rectangle {
                            id: customSwatch
                            anchors.top: parent.top
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: parent.width
                            height: 26
                            radius: 6
                            border.width: customCell.selected ? 2 : 1
                            border.color: customCell.selected
                                ? Theme.fg
                                : customMouse.containsMouse
                                    ? Qt.alpha(Theme.fg, 0.55)
                                    : Qt.alpha(Theme.fg, 0.16)
                            Behavior on border.color { ColorAnimation { duration: 120 } }

                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.00; color: "#ff4d4d" }
                                GradientStop { position: 0.17; color: "#ffb84d" }
                                GradientStop { position: 0.33; color: "#ffe94d" }
                                GradientStop { position: 0.50; color: "#4dff88" }
                                GradientStop { position: 0.67; color: "#4dd2ff" }
                                GradientStop { position: 0.83; color: "#8a7dff" }
                                GradientStop { position: 1.00; color: "#ff6bd6" }
                            }
                        }

                        Text {
                            anchors.top: customSwatch.bottom
                            anchors.topMargin: 3
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Custom"
                            color: customCell.selected || customMouse.containsMouse
                                ? Theme.accent
                                : Qt.alpha(Theme.fg, 0.55)
                            font.family: Theme.fontFamily
                            font.pixelSize: 9
                        }

                        MouseArea {
                            id: customMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.toggleCustom()
                        }
                    }
                }
            }

            // collapsible custom accent picker (inline, not a popup)
            Item {
                id: customPanel
                width: parent.width
                height: root.customOpen ? 190 : 0
                visible: height > 0
                clip: true
                Behavior on height { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: Qt.alpha(Theme.fg, 0.05)
                    border.width: 1
                    border.color: Qt.alpha(Theme.fg, 0.08)
                }

                Column {
                    anchors.fill: parent
                    anchors.margins: 4
                    spacing: 4

                    Item {
                        width: parent.width
                        height: 18

                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Custom color"
                            color: Theme.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: 12
                            font.bold: true
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: "✕"
                            color: closeCustom.containsMouse ? Theme.fg : Qt.alpha(Theme.fg, 0.55)
                            font.family: Theme.fontFamily
                            font.pixelSize: 13

                            MouseArea {
                                id: closeCustom
                                anchors.fill: parent
                                anchors.margins: -6
                                hoverEnabled: true
                                onClicked: root.customOpen = false
                            }
                        }
                    }

                    Row {
                        width: parent.width
                        height: 140
                        spacing: 10

                        // saturation / brightness field
                        Rectangle {
                            id: svArea
                            width: 140
                            height: 140
                            color: "transparent"

                            Canvas {
                                id: svCanvas
                                anchors.fill: parent
                                property color hueColor: hsvToHex(root.customHue, 1, 1)
                                onHueColorChanged: requestPaint()
                                onWidthChanged: requestPaint()
                                onHeightChanged: requestPaint()
                                onVisibleChanged: requestPaint()

                                onPaint: {
                                    const ctx = getContext("2d")
                                    ctx.clearRect(0, 0, width, height)

                                    // rounded clip so the field matches its frame
                                    const r = 8
                                    ctx.beginPath()
                                    ctx.moveTo(r, 0)
                                    ctx.lineTo(width - r, 0)
                                    ctx.quadraticCurveTo(width, 0, width, r)
                                    ctx.lineTo(width, height - r)
                                    ctx.quadraticCurveTo(width, height, width - r, height)
                                    ctx.lineTo(r, height)
                                    ctx.quadraticCurveTo(0, height, 0, height - r)
                                    ctx.lineTo(0, r)
                                    ctx.quadraticCurveTo(0, 0, r, 0)
                                    ctx.closePath()
                                    ctx.clip()

                                    ctx.fillStyle = hsvToHex(root.customHue, 1, 1)
                                    ctx.fillRect(0, 0, width, height)

                                    const white = ctx.createLinearGradient(0, 0, width, 0)
                                    white.addColorStop(0, "#ffffff")
                                    white.addColorStop(1, "rgba(255,255,255,0)")
                                    ctx.fillStyle = white
                                    ctx.fillRect(0, 0, width, height)

                                    const black = ctx.createLinearGradient(0, 0, 0, height)
                                    black.addColorStop(0, "rgba(0,0,0,0)")
                                    black.addColorStop(1, "#000000")
                                    ctx.fillStyle = black
                                    ctx.fillRect(0, 0, width, height)
                                }
                            }

                            Rectangle {
                                anchors.fill: parent
                                radius: 8
                                color: "transparent"
                                border.width: 1
                                border.color: Qt.alpha(Theme.fg, 0.16)
                            }

                            Rectangle {
                                x: Math.min(Math.max(
                                        root.customSat / 100 * svArea.width,
                                        width / 2),
                                        svArea.width - width / 2) - width / 2
                                y: Math.min(Math.max(
                                        (1 - root.customVal / 100) * svArea.height,
                                        height / 2),
                                        svArea.height - height / 2) - height / 2
                                width: 14
                                height: 14
                                radius: 7
                                color: "#00000033"
                                border.width: 2
                                border.color: "#ffffff"
                            }

                            MouseArea {
                                anchors.fill: parent

                                function pick(mx, my) {
                                    root.customSat = Math.round(Math.min(Math.max(
                                        mx / width, 0), 1) * 100)
                                    root.customVal = Math.round((1 - Math.min(Math.max(
                                        my / height, 0), 1)) * 100)
                                }

                                onPressed: mouse => pick(mouse.x, mouse.y)
                                onPositionChanged: mouse => {
                                    if (pressed)
                                        pick(mouse.x, mouse.y)
                                }
                            }
                        }

                        Column {
                            width: parent.width - svArea.width - parent.spacing
                            height: parent.height
                            spacing: 8

                            Row {
                                spacing: 10

                                Rectangle {
                                    id: customPreview
                                    width: 54
                                    height: 22
                                    radius: 6
                                    color: root.customHex
                                    border.width: 1
                                    border.color: Qt.alpha(Theme.fg, 0.25)
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: root.customHex.toUpperCase()
                                    color: Theme.fg
                                    font.family: Theme.fontFamily
                                    font.pixelSize: 11
                                    font.bold: true
                                }
                            }

                            Text {
                                text: "Hue"
                                color: Qt.alpha(Theme.fg, 0.6)
                                font.family: Theme.fontFamily
                                font.pixelSize: 10
                            }

                            Item {
                                width: parent.width
                                height: 16

                                Rectangle {
                                    id: hueBar
                                    anchors.fill: parent
                                    radius: 5
                                    border.width: 1
                                    border.color: Qt.alpha(Theme.fg, 0.16)
                                    gradient: Gradient {
                                        orientation: Gradient.Horizontal
                                        GradientStop { position: 0.00; color: "#ff0000" }
                                        GradientStop { position: 0.17; color: "#ffff00" }
                                        GradientStop { position: 0.33; color: "#00ff00" }
                                        GradientStop { position: 0.50; color: "#00ffff" }
                                        GradientStop { position: 0.67; color: "#0000ff" }
                                        GradientStop { position: 0.83; color: "#ff00ff" }
                                        GradientStop { position: 1.00; color: "#ff0000" }
                                    }
                                }

                                Rectangle {
                                    x: Math.min(Math.max(
                                            root.customHue / 360 * hueBar.width,
                                            width / 2),
                                            hueBar.width - width / 2) - width / 2
                                    anchors.verticalCenter: hueBar.verticalCenter
                                    width: 10
                                    height: 20
                                    radius: 5
                                    color: "#00000055"
                                    border.width: 2
                                    border.color: "#ffffff"
                                }

                                MouseArea {
                                    anchors.fill: parent

                                    function pick(mx) {
                                        root.customHue = Math.round(Math.min(Math.max(
                                            mx / width, 0), 1) * 360)
                                    }

                                    onPressed: mouse => pick(mouse.x)
                                    onPositionChanged: mouse => {
                                        if (pressed)
                                            pick(mouse.x)
                                    }
                                }
                            }

                            Text {
                                text: "Saturation × brightness"
                                color: Qt.alpha(Theme.fg, 0.4)
                                font.family: Theme.fontFamily
                                font.pixelSize: 9
                            }

                            Row {
                                spacing: 8

                                Rectangle {
                                    width: 90
                                    height: 24
                                    radius: 6
                                    color: root.customHex
                                    border.width: 1
                                    border.color: Qt.alpha(Theme.fg, 0.2)

                                    Text {
                                        anchors.centerIn: parent
                                        text: "Apply"
                                        color: root.customVal > 55 ? Theme.bg : Theme.fg
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 10
                                        font.bold: true
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: root.applyCustom()
                                    }
                                }

                                Rectangle {
                                    width: 90
                                    height: 24
                                    radius: 6
                                    color: "transparent"
                                    border.width: 1
                                    border.color: Qt.alpha(Theme.fg, 0.3)

                                    Text {
                                        anchors.centerIn: parent
                                        text: "Cancel"
                                        color: Theme.fg
                                        font.family: Theme.fontFamily
                                        font.pixelSize: 10
                                    }

                                    MouseArea {
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        onClicked: root.customOpen = false
                                    }
                                }
                            }
                        }
                    }
                }
            }

            GridView {
                id: grid
                width: parent.width
                height: parent.height - themeBlock.height - customPanel.height
                        - (customPanel.height > 0 ? parent.spacing : 0)
                clip: true
                cellWidth: 176
                cellHeight: 103
                cacheBuffer: 4000
                model: root.wallpapers

                delegate: Item {
                    id: cell
                    required property string modelData
                    readonly property bool busy: root.applyingPath === modelData
                    width: grid.cellWidth
                    height: grid.cellHeight

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        radius: 6
                        color: Qt.alpha(Theme.fg, 0.06)

                        Image {
                            anchors.fill: parent
                            anchors.margins: 1
                            source: "file://" + cell.modelData
                            sourceSize.width: 340
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            clip: true
                        }

                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: "transparent"
                            border.width: cell.busy ? 3 : mouse.containsMouse ? 2 : 0
                            border.color: cell.busy ? Theme.accent : Qt.alpha(Theme.accent, 0.8)

                            SequentialAnimation on opacity {
                                running: cell.busy
                                loops: Animation.Infinite
                                alwaysRunToEnd: true
                                NumberAnimation { to: 0.4; duration: 350 }
                                NumberAnimation { to: 1.0; duration: 350 }
                            }
                        }

                        MouseArea {
                            id: mouse
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.apply(cell.modelData)
                        }
                    }
                }
            }
        }

    }

    // --- palette math ---

    function rgbToHsl(r, g, b) {
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b)
        const l = (mx + mn) / 2
        if (mx === mn)
            return [0, 0, l]
        const d = mx - mn
        const s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn)
        let h
        if (mx === r) h = ((g - b) / d + (g < b ? 6 : 0))
        else if (mx === g) h = (b - r) / d + 2
        else h = (r - g) / d + 4
        return [h * 60, s, l]
    }

    function hslToHex(h, s, l) {
        h = ((h % 360) + 360) % 360
        const c = (1 - Math.abs(2 * l - 1)) * s
        const x = c * (1 - Math.abs((h / 60) % 2 - 1))
        const m = l - c / 2
        let r, g, b
        if (h < 60) { r = c; g = x; b = 0 }
        else if (h < 120) { r = x; g = c; b = 0 }
        else if (h < 180) { r = 0; g = c; b = x }
        else if (h < 240) { r = 0; g = x; b = c }
        else if (h < 300) { r = x; g = 0; b = c }
        else { r = c; g = 0; b = x }
        const to = v => Math.round((v + m) * 255).toString(16).padStart(2, "0")
        return "#" + to(r) + to(g) + to(b)
    }

    function rgbToHsv(r, g, b) {
        const mx = Math.max(r, g, b), mn = Math.min(r, g, b)
        const d = mx - mn
        let h = 0
        if (d !== 0) {
            if (mx === r) h = ((g - b) / d + (g < b ? 6 : 0))
            else if (mx === g) h = (b - r) / d + 2
            else h = (r - g) / d + 4
            h *= 60
        }
        return [h, mx === 0 ? 0 : d / mx, mx]
    }

    function hsvToHex(h, s, v) {
        h = ((h % 360) + 360) % 360
        const c = v * s
        const x = c * (1 - Math.abs((h / 60) % 2 - 1))
        const m = v - c
        let r, g, b
        if (h < 60) { r = c; g = x; b = 0 }
        else if (h < 120) { r = x; g = c; b = 0 }
        else if (h < 180) { r = 0; g = c; b = x }
        else if (h < 240) { r = 0; g = x; b = c }
        else if (h < 300) { r = x; g = 0; b = c }
        else { r = c; g = 0; b = x }
        const to = val => Math.round((val + m) * 255).toString(16).padStart(2, "0")
        return "#" + to(r) + to(g) + to(b)
    }

    function hueDist(a, b) {
        const d = Math.abs(a - b) % 360
        return d > 180 ? 360 - d : d
    }

    function finish(d) {
        // histogram: 4 bits/channel → up to 4096 bins, averaged per bin
        const bins = new Map()
        let total = 0
        for (let i = 0; i < d.length; i += 4) {
            if (d[i + 3] < 200)
                continue
            total++
            const key = (d[i] >> 4 << 8) | (d[i + 1] >> 4 << 4) | (d[i + 2] >> 4)
            let e = bins.get(key)
            if (!e) bins.set(key, e = [0, 0, 0, 0])
            e[0]++; e[1] += d[i]; e[2] += d[i + 1]; e[3] += d[i + 2]
        }
        if (total === 0)
            return
        const clusters = [...bins.values()].map(e => {
            const [h, s, l] = rgbToHsl(e[1] / e[0] / 255, e[2] / e[0] / 255, e[3] / e[0] / 255)
            return { n: e[0], h, s, l }
        }).sort((a, b) => b.n - a.n).slice(0, 40)

        // mode detection: designed artwork (theme wallpapers, logos) packs
        // its pixels into a few flat-color clusters — its palette IS the
        // image, so trust the artist's values (fidelity). Photographs smear
        // across hundreds of bins — no designed palette exists, so interpret
        // with the pastel tuning modeled on nord/everforest.
        const art = clusters.slice(0, 8).reduce((s, c) => s + c.n, 0) / total > 0.85

        // bg: dominant dark cluster, clamped deep for contrast
        let bgC = clusters[0]
        let best = -1
        for (const c of clusters) {
            const score = c.n * (1.15 - c.l)
            if (score > best) { best = score; bgC = c }
        }
        const bgH = bgC.h, bgS = Math.min(bgC.s, art ? 0.35 : 0.26)
        const bgL = art ? Math.min(Math.max(bgC.l, 0.09), 0.2)
                        : Math.min(Math.max(bgC.l * 0.7, 0.1), 0.17)

        // beacon: a tiny bright hue-distinct cluster reads as a light
        // source (lamp, neon, sunset sliver) — semantically the image's
        // accent even though a histogram barely sees it. Scanned over all
        // bins: a beacon is exactly the thing too small for the top-40.
        // Bounds: bright against the ground, some color (glows run
        // desaturated), and rare — common enough and the normal primary
        // pass already owns it.
        let bea = null
        {
            const cand = []
            for (const e of bins.values()) {
                const [h, s, l] = rgbToHsl(e[1] / e[0] / 255, e[2] / e[0] / 255, e[3] / e[0] / 255)
                if (s >= 0.15 && l >= bgC.l + 0.3 && hueDist(h, bgH) >= 50)
                    cand.push({ n: e[0], h, s, l })
            }
            if (cand.length) {
                const seed = cand.reduce((a, c) => c.l * c.n > a.l * a.n ? c : a)
                let n = 0, ss = 0, ls = 0
                for (const c of cand)
                    if (hueDist(c.h, seed.h) <= 30) { n += c.n; ss += c.s * c.n; ls += c.l * c.n }
                if (n / total >= 0.0005 && n / total <= 0.02)
                    bea = { n, h: seed.h, s: Math.max(ss / n, 0.45), l: ls / n }
            }
        }

        // primary: the beacon when there is one — else the most vibrant
        // thing with real presence. The secondary pass below then picks
        // up the dominant field hue on its own.
        let priC = bea
        best = 0
        if (!priC)
            for (const c of clusters) {
                const mid = (c.l > 0.15 && c.l < 0.85) ? 1 : 0.2
                const score = Math.pow(c.s, 1.5) * Math.sqrt(c.n / total) * mid
                if (c.s > 0.15 && score > best) { best = score; priC = c }
            }
        const priH = priC ? priC.h : bgH
        const priS = priC ? (art ? Math.min(Math.max(priC.s, 0.3), 0.85)
                                 : Math.min(Math.max(priC.s, 0.3), 0.55)) : 0.15
        const priL = priC ? (art ? Math.min(Math.max(priC.l, 0.45), 0.75)
                                 : Math.min(Math.max(priC.l, 0.62), 0.78)) : 0.7

        // secondary: vibrant and hue-distinct from primary, else shifted primary
        let secC = null
        best = 0
        for (const c of clusters) {
            if (c.s < 0.2 || hueDist(c.h, priH) < 45)
                continue
            const score = c.s * Math.sqrt(c.n / total)
            if (score > best) { best = score; secC = c }
        }
        const secH = secC ? secC.h : priH + 35
        const secS = secC ? (art ? Math.min(Math.max(secC.s, 0.25), 0.75)
                                 : Math.min(Math.max(secC.s, 0.2), 0.4)) : priS * 0.7
        const secL = secC ? (art ? Math.min(Math.max(secC.l, 0.45), 0.8)
                                 : Math.min(Math.max(secC.l, 0.7), 0.8)) : 0.74

        // alert: reddest cluster if the image has one, else a stock red
        let alC = null
        for (const c of clusters) {
            if ((c.h <= 20 || c.h >= 340) && c.s > 0.35 && (!alC || c.n > alC.n))
                alC = c
        }
        const alert = alC ? (art ? hslToHex(alC.h, Math.min(Math.max(alC.s, 0.4), 0.8),
                                            Math.min(Math.max(alC.l, 0.5), 0.65))
                                 : hslToHex(alC.h, Math.min(Math.max(alC.s, 0.35), 0.45), 0.66))
                          : hslToHex(4, 0.4, 0.66)

        // fg: warm cream (everforest-style) rather than near-white — borrow
        // the image's warmest muted hue when it has one, else a stock beige
        let fgH = 42
        for (const c of clusters) {
            if (c.h >= 20 && c.h <= 60 && c.l > 0.3) { fgH = c.h; break }
        }

        const palette = [
            hslToHex(bgH, bgS, bgL),                    // bg
            hslToHex(bgH, bgS, bgL + 0.06),             // altbg
            hslToHex(fgH, 0.2, 0.78),                   // fg
            hslToHex(priH, 0.18, bgL + 0.1),            // border
            hslToHex(priH, priS, priL),                 // primary
            hslToHex(secH, secS, secL),                 // secondary
            alert,                                      // alert
            hslToHex(bgH, 0.1, 0.4)                     // disabled
        ]

        // terminal ANSI palette (kitty): image hues placed in their nearest
        // SEMANTIC slot — green things stay green, blue things blue — so
        // color-coded output (diffs, ls, test runners) keeps meaning on any
        // wallpaper. The red slot keeps the alert hue; slots the image has
        // no hue near are synthesized at the slot's anchor hue.
        const terms = new Array(6)
        terms[0] = alC ? alC : { h: 4, s: 0.4, l: 0.66 }
        const anchors = [[1, 120], [2, 55], [3, 225], [4, 300], [5, 180]]
        const cands = clusters
            .filter(c => c.s > 0.2 && c.l > 0.15 && c.l < 0.85
                && hueDist(c.h, terms[0].h) >= 30)
            .sort((a, b) => b.s * Math.sqrt(b.n) - a.s * Math.sqrt(a.n))
            .slice(0, 8)
        for (let pass = 0; pass < anchors.length; pass++) {
            // greedy best pair; unmatched slots (dist > 45) get synthesized
            let bi = -1, bc = -1, bd = 46
            for (const [i, a] of anchors) {
                if (terms[i]) continue
                for (let j = 0; j < cands.length; j++)
                    if (cands[j] && hueDist(cands[j].h, a) < bd) {
                        bd = hueDist(cands[j].h, a); bi = i; bc = j
                    }
            }
            if (bi < 0) break
            terms[bi] = cands[bc]; cands[bc] = null
        }
        // synthesized slots speak more softly than hues the image earned
        for (const [i, a] of anchors)
            if (!terms[i]) terms[i] = { h: a, s: art ? 0.5 : 0.4, l: 0.62 }

        const ansi = new Array(16)
        ansi[0] = hslToHex(bgH, bgS, bgL + 0.06)
        ansi[7] = hslToHex(fgH, 0.15, 0.72)
        ansi[8] = hslToHex(bgH, 0.1, 0.38)
        ansi[15] = hslToHex(fgH, 0.18, 0.86)
        for (let i = 0; i < 6; i++) {
            const t = terms[i]
            // fidelity: each hue keeps its own body; pastel: uniform wash
            const s = art ? Math.min(Math.max(t.s, 0.35), 0.8) : 0.4
            const l = art ? Math.min(Math.max(t.l, 0.5), 0.7) : 0.66
            ansi[i + 1] = hslToHex(t.h, s, l)
            ansi[i + 9] = hslToHex(t.h, art ? s : 0.42, Math.min(l + 0.08, 0.78))
        }

        Quickshell.execDetached(
            [Theme.configDir + "/scripts/set-wallpaper", root.applyingPath]
                .concat(palette).concat(ansi))
        root.applyingPath = ""
        root.visible = false
    }
}
