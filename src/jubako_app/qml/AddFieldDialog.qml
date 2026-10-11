import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Add a field to the open table. Lives at page level (not inside the Fields
// dialog): a dialog inside another modal dialog is unreliable in Qt Quick.
Dialog {
    id: dialog
    objectName: "addFieldDialog"
    property string error: ""
    property bool nameTouched: false
    property bool returnToFields: false   // reopen the Fields list when done
    property var targets: []               // tables a lookup can point at, each with its words fields
    readonly property bool isLookup: typeBox.currentValue === "lookup"
    readonly property var targetFields: targetBox.currentIndex >= 0 && targets.length > 0
        ? targets[targetBox.currentIndex].fields : []

    function openFor(fromFields) {
        returnToFields = !!fromFields
        labelField.text = ""
        nameField.text = ""
        nameTouched = false
        typeBox.currentIndex = 0
        uniqueBox.checked = false
        targets = Bridge.lookupTargets()
        targetBox.currentIndex = targets.length > 0 ? 0 : -1
        error = ""
        open()
        labelField.forceActiveFocus()
    }

    function go() {
        let r
        if (isLookup) {
            if (targets.length === 0) { error = "There is no other table to point at yet."; return }
            r = Bridge.addLookupField(labelField.text.trim(), nameField.text.trim(),
                                      targets[targetBox.currentIndex].name, showBox.currentValue)
        } else {
            const unique = uniqueBox.checked && typeBox.currentValue !== "boolean"
            r = Bridge.addField(labelField.text.trim(), nameField.text.trim(), typeBox.currentValue, unique)
        }
        if (!r.ok) { error = r.error; return }
        close()
        if (returnToFields) fieldsDialog.openFor()
    }

    title: "Add a field to " + Bridge.currentTable
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: 460
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 8
        Label { text: "Label"; font.bold: true }
        TextField {
            id: labelField
            objectName: "addFieldLabel"
            Layout.fillWidth: true
            placeholderText: "What people see, like Moved"
            onTextEdited: { if (!dialog.nameTouched) nameField.text = Bridge.slugName(text) }
            onAccepted: dialog.go()
        }
        Label { text: "Name inside the database"; font.bold: true; Layout.topMargin: 6 }
        TextField {
            id: nameField
            objectName: "addFieldName"
            Layout.fillWidth: true
            font.family: Theme.monoFont
            placeholderText: "made from the label"
            onTextEdited: dialog.nameTouched = true
            onAccepted: dialog.go()
        }
        Label { text: "Type"; font.bold: true; Layout.topMargin: 6 }
        ComboBox {
            id: typeBox
            objectName: "addFieldType"
            Layout.preferredWidth: 240
            model: Bridge.allFieldTypes()
            textRole: "label"
            valueRole: "key"
        }
        // A lookup: which table it points at, and which of that table's words fields it shows.
        GridLayout {
            visible: dialog.isLookup
            columns: 2
            columnSpacing: 10
            rowSpacing: 6
            Label { text: "Points at" }
            ComboBox {
                id: targetBox
                objectName: "addFieldTarget"
                Layout.preferredWidth: 240
                model: dialog.targets
                textRole: "name"
                onActivated: showBox.currentIndex = 0
            }
            Label { text: "Shows" }
            ComboBox {
                id: showBox
                objectName: "addFieldShow"
                Layout.preferredWidth: 240
                model: dialog.targetFields
                textRole: "label"
                valueRole: "name"
            }
        }
        Label {
            Layout.fillWidth: true
            visible: dialog.isLookup
            text: dialog.targets.length === 0
                ? "There is no other table with a words field to point at yet."
                : "Each row picks one row of " + targetBox.currentText + " and shows its " + showBox.currentText + "."
            color: Theme.lightForeground
            font.pointSize: 10
            wrapMode: Text.WordWrap
        }
        CheckBox {
            id: uniqueBox
            objectName: "addFieldUnique"
            visible: typeBox.currentValue !== "boolean" && !dialog.isLookup
            text: "No repeats: no two rows the same (like an email or a code)"
        }
        Label {
            Layout.fillWidth: true
            text: "Rows already there will have nothing in the new field."
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
            text: "Add it"
            objectName: "addFieldGo"
            primary: true
            enabled: labelField.text.trim() !== "" || nameField.text.trim() !== ""
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: dialog.go()
        }
    }
    onRejected: { if (returnToFields) fieldsDialog.openFor() }
}
