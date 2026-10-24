import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Make an empty table: its name, and a line per field (label, type, no repeats).
// More fields, or a lookup, can be added afterwards with Add field.
Dialog {
    id: dialog
    objectName: "newTableDialog"
    property string error: ""
    readonly property var types: Bridge.fieldTypes()

    function openFor() {
        nameField.text = ""
        fieldRows.clear()
        addLine()
        error = ""
        open()
        nameField.forceActiveFocus()
    }

    function addLine() {
        fieldRows.append({ label: "", kind: "text", unique: false })
    }

    function go() {
        const fields = []
        for (let i = 0; i < fieldRows.count; i++) {
            const row = fieldRows.get(i)
            fields.push({ label: row.label.trim(), type: row.kind, unique: row.unique && row.kind !== "boolean" })
        }
        const r = Bridge.newTable(nameField.text.trim(), fields)
        if (!r.ok) { error = r.error; return }
        close()
        page.mode = "grid"
    }

    ListModel { id: fieldRows; objectName: "newTableFields" }

    title: "Make a new table"
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: 560
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 8
        Label { text: "Name"; font.bold: true }
        TextField {
            id: nameField
            objectName: "newTableName"
            Layout.fillWidth: true
            placeholderText: "What it holds, like Vet visits"
            onAccepted: dialog.go()
        }
        Label {
            Layout.fillWidth: true
            readonly property string inside: Bridge.tableName(nameField.text)
            visible: inside !== "" && inside !== nameField.text.trim()
            text: "Inside the database it is called " + inside + "."
            color: Theme.lightForeground
            font.pointSize: 10
            wrapMode: Text.WordWrap
        }

        Label { text: "Fields"; font.bold: true; Layout.topMargin: 6 }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(lines.implicitHeight, 300)
            clip: true
            ColumnLayout {
                id: lines
                width: scroll.availableWidth
                spacing: 6
                Repeater {
                    model: fieldRows
                    delegate: RowLayout {
                        id: line
                        required property int index
                        required property string label
                        required property string kind
                        required property bool unique
                        Layout.fillWidth: true
                        spacing: 8
                        TextField {
                            objectName: "newTableFieldLabel" + line.index
                            Layout.fillWidth: true
                            text: line.label
                            placeholderText: line.index === 0 ? "Like Name" : "Another field"
                            onTextEdited: fieldRows.setProperty(line.index, "label", text)
                            onAccepted: dialog.go()
                        }
                        ComboBox {
                            objectName: "newTableFieldType" + line.index
                            Layout.preferredWidth: 190
                            model: dialog.types
                            textRole: "label"
                            valueRole: "key"
                            currentIndex: indexOfValue(line.kind)
                            onActivated: fieldRows.setProperty(line.index, "kind", currentValue)
                        }
                        CheckBox {
                            text: "No repeats"
                            enabled: line.kind !== "boolean"
                            checked: line.unique && line.kind !== "boolean"
                            onToggled: fieldRows.setProperty(line.index, "unique", checked)
                        }
                        ToolButton {
                            text: "✕"
                            enabled: fieldRows.count > 1
                            onClicked: fieldRows.remove(line.index)
                        }
                    }
                }
            }
        }
        ActionButton {
            text: "Add another field"
            objectName: "newTableAddLine"
            onClicked: dialog.addLine()
        }
        Label {
            Layout.fillWidth: true
            text: "A row number is added for you. You can add, rename or delete fields later."
            color: Theme.lightForeground
            font.pointSize: 10
            wrapMode: Text.WordWrap
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
            DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
        }
        ActionButton {
            text: "Make the table"
            objectName: "newTableGo"
            primary: true
            enabled: nameField.text.trim() !== ""
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: dialog.go()
        }
    }
}
