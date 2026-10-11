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

    function openFor(fromFields) {
        returnToFields = !!fromFields
        labelField.text = ""
        nameField.text = ""
        nameTouched = false
        typeBox.currentIndex = 0
        uniqueBox.checked = false
        error = ""
        open()
        labelField.forceActiveFocus()
    }

    function go() {
        const unique = uniqueBox.checked && typeBox.currentValue !== "boolean"
        const r = Bridge.addField(labelField.text.trim(), nameField.text.trim(), typeBox.currentValue, unique)
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
            model: Bridge.fieldTypes()
            textRole: "label"
            valueRole: "key"
        }
        CheckBox {
            id: uniqueBox
            objectName: "addFieldUnique"
            visible: typeBox.currentValue !== "boolean"
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
