import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Home: four big buttons and the databases you opened lately.
Page {
    id: page
    property var recentList: []

    function reload() { recentList = Bridge.recent() }
    Component.onCompleted: reload()
    StackView.onActivated: reload()

    background: Rectangle { color: Theme.window }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 40
        spacing: 20

        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Jubako"
                font.pointSize: 30
                font.bold: true
            }
            ActionButton { text: "About"; objectName: "homeAbout"; onClicked: win.showAbout() }
        }
        Label {
            Layout.fillWidth: true
            text: "A simple database. Make one, put a spreadsheet in it, look at your rows."
            font.pointSize: 13
            color: Theme.lightForeground
            wrapMode: Text.WordWrap
        }

        Flow {
            Layout.fillWidth: true
            Layout.topMargin: 8
            spacing: 16
            BigButton { text: "New database"; hint: "Start with nothing in it"; primary: true; onClicked: win.startNew() }
            BigButton { text: "Start from a template"; hint: "Contacts, stock, projects and more"; onClicked: win.startTemplate() }
            BigButton { text: "Open a database"; hint: "One you already made"; onClicked: win.startOpen() }
            BigButton { text: "Import a spreadsheet"; hint: "A CSV or Excel file becomes a database"; onClicked: win.startImport() }
        }

        Label {
            Layout.topMargin: 16
            text: "Recent"
            font.pointSize: 15
            font.bold: true
            visible: page.recentList.length > 0
        }

        ListView {
            id: recentView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: page.recentList
            visible: page.recentList.length > 0
            ScrollBar.vertical: ScrollBar {}

            delegate: ItemDelegate {
                id: item
                required property int index
                required property var modelData
                width: recentView.width
                height: 62
                hoverEnabled: true
                onClicked: win.openRecent(index)

                background: Rectangle {
                    radius: 8
                    color: item.down ? Theme.selection
                         : item.hovered ? Theme.lighterBackground : "transparent"
                }
                contentItem: RowLayout {
                    spacing: 14
                    Rectangle {
                        width: 40; height: 40; radius: 8
                        color: Theme.lighterBackground
                        Label {
                            anchors.centerIn: parent
                            text: item.modelData.backend === "sqlite" ? "▦" : "☁"
                            font.pointSize: 16
                            color: Theme.accent
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Label {
                            Layout.fillWidth: true
                            text: item.modelData.title
                            font.pointSize: 12
                            font.bold: true
                            elide: Text.ElideRight
                        }
                        Label {
                            Layout.fillWidth: true
                            text: item.modelData.backendWord + "  ·  " + (item.modelData.path || item.modelData.where)
                            color: Theme.lightForeground
                            font.pointSize: 10
                            elide: Text.ElideMiddle
                        }
                    }
                }
            }
        }

        EmptyState {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.recentList.length === 0
            title: "Nothing here yet"
            text: "Drop a spreadsheet on this window and it becomes a database. Or press New database above."
        }
    }
}
