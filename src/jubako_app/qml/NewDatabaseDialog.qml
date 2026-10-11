import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// "New database": what to start with (nothing, or a template), and where it lives.
// A file is the default and needs nothing.
// The same dialog connects to a remembered server ("open" mode), because a
// password is never saved and has to be typed again.
Dialog {
    id: dialog
    objectName: "newDatabaseDialog"
    property string mode: "new"          // "new" or "open"
    property string backend: "sqlite"
    property string chosenTitle: ""
    property var backendList: []
    property var templateList: []
    property string templateKey: ""      // "" for an empty database
    property alias sampleRows: sampleBox.checked
    property string error: ""
    signal sqliteChosen(string chosenTitle)

    function templateInfo() {
        for (const t of templateList) if (t.key === templateKey) return t
        return null
    }

    function openFor(theMode, theBackend, theTitle, connection, theTemplate) {
        mode = theMode
        backendList = Bridge.backends()
        templateList = Bridge.templates()
        templateKey = theTemplate || ""
        sampleBox.checked = true
        backend = theBackend || "sqlite"
        error = ""
        nameField.text = theTitle || ""
        hostField.text = connection.host || "localhost"
        portField.text = connection.port || ""
        dbField.text = connection.database || ""
        userField.text = connection.user || ""
        passField.text = ""
        open()
    }

    function go() {
        error = ""
        if (backend === "sqlite") {
            const t = templateInfo()
            chosenTitle = nameField.text || (t ? t.title : "")
            close()
            sqliteChosen(chosenTitle)
            return
        }
        const connection = {
            "host": hostField.text, "port": portField.text, "database": dbField.text,
            "user": userField.text, "password": passField.text
        }
        const r = mode === "open"
            ? Bridge.openDatabase(backend, "", connection)
            : templateKey !== ""
            ? Bridge.newFromTemplate(backend, "", nameField.text, connection, templateKey, sampleBox.checked)
            : Bridge.newDatabase(backend, "", nameField.text, connection)
        if (r.ok)
            close()
        else
            error = r.error
    }

    title: mode === "open" ? "Connect to your server" : "New database"
    modal: true
    anchors.centerIn: parent
    width: 600
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 10

        Label {
            visible: dialog.mode === "new"
            text: "What should it start with?"
            font.pointSize: 12
            font.bold: true
        }
        ComboBox {
            id: templateBox
            objectName: "templateBox"
            visible: dialog.mode === "new"
            Layout.fillWidth: true
            model: ["Nothing: an empty database"].concat(dialog.templateList.map(t => "Template: " + t.title))
            currentIndex: Math.max(0, dialog.templateList.findIndex(t => t.key === dialog.templateKey) + 1)
            onActivated: function(i) { dialog.templateKey = i === 0 ? "" : dialog.templateList[i - 1].key }
        }
        Label {
            visible: dialog.mode === "new" && dialog.templateKey !== ""
            Layout.fillWidth: true
            text: {
                const t = dialog.templateInfo()
                return t ? t.blurb + " Comes with saved views and reports. Tables: " + t.tables.join(", ") + "." : ""
            }
            color: Theme.lightForeground
            font.pointSize: 10
            wrapMode: Text.WordWrap
        }
        CheckBox {
            id: sampleBox
            objectName: "sampleBox"
            visible: dialog.mode === "new" && dialog.templateKey !== ""
            text: "Put in a few made-up example rows (delete them when you are ready)"
            checked: true
        }

        Label {
            visible: dialog.mode === "new"
            Layout.topMargin: 6
            text: "Where should it live?"
            font.pointSize: 12
            font.bold: true
        }

        Repeater {
            model: dialog.mode === "new" ? dialog.backendList : []
            delegate: ColumnLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: 0
                RadioButton {
                    text: modelData.title
                    checked: dialog.backend === modelData.key
                    enabled: modelData.ready
                    onClicked: dialog.backend = modelData.key
                }
                Label {
                    Layout.fillWidth: true
                    Layout.leftMargin: 34
                    text: modelData.ready ? modelData.blurb
                        : modelData.blurb + "  (Install " + modelData.driver + " first.)"
                    color: Theme.lightForeground
                    font.pointSize: 10
                    wrapMode: Text.WordWrap
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.topMargin: 8
            columns: 2
            columnSpacing: 12
            rowSpacing: 8

            Label { text: "Name"; visible: dialog.mode === "new" }
            TextField {
                id: nameField
                Layout.fillWidth: true
                visible: dialog.mode === "new"
                placeholderText: dialog.templateKey !== "" ? "Optional. \u201c" + (dialog.templateInfo() || {}).title + "\u201d if blank."
                               : dialog.backend === "sqlite" ? "Optional. The file name is used if blank." : "What to call this database"
            }

            Label { text: "Server address"; visible: dialog.backend !== "sqlite" }
            TextField { id: hostField; Layout.fillWidth: true; visible: dialog.backend !== "sqlite"; placeholderText: "localhost" }

            Label { text: "Port"; visible: dialog.backend !== "sqlite" }
            TextField {
                id: portField
                Layout.preferredWidth: 120
                visible: dialog.backend !== "sqlite"
                placeholderText: dialog.backend === "postgres" ? "5432" : "3306"
                validator: IntValidator { bottom: 1; top: 65535 }
            }

            Label { text: "Database"; visible: dialog.backend !== "sqlite" }
            TextField { id: dbField; Layout.fillWidth: true; visible: dialog.backend !== "sqlite"; placeholderText: "The database on that server (it must already exist)" }

            Label { text: "User"; visible: dialog.backend !== "sqlite" }
            TextField { id: userField; Layout.fillWidth: true; visible: dialog.backend !== "sqlite" }

            Label { text: "Password"; visible: dialog.backend !== "sqlite" }
            TextField {
                id: passField
                Layout.fillWidth: true
                visible: dialog.backend !== "sqlite"
                echoMode: TextInput.Password
                placeholderText: "Not saved. Ask again next time."
                onAccepted: dialog.go()
            }
        }

        Label {
            Layout.fillWidth: true
            visible: dialog.error !== ""
            text: dialog.error
            color: Theme.red
            wrapMode: Text.WordWrap
        }
    }

    footer: DialogButtonBox {
        ActionButton {
            text: "Cancel"
            onClicked: dialog.reject()
        }
        ActionButton {
            text: dialog.backend === "sqlite" ? "Next" : (dialog.mode === "open" ? "Open it" : "Make it")
            primary: true
            onClicked: dialog.go()
        }
    }
}
