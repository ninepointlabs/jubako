import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Turn a words field into a lookup: "Customer" names in orders become rows of
// customers. Values that match no row are listed first, with an offer to add
// them to the other table. Lives at page level, like Add field.
Dialog {
    id: dialog
    objectName: "makeLookupDialog"
    property var field: ({})
    property var targets: []
    property var missing: []
    property string error: ""
    readonly property var targetFields: targetBox.currentIndex >= 0 && targets.length > 0
        ? targets[targetBox.currentIndex].fields.filter(f => !(targets[targetBox.currentIndex].name === Bridge.currentTable && f.name === dialog.field.name))
        : []

    function openFor(theField) {
        field = theField
        targets = Bridge.lookupTargets().filter(t => t.name !== Bridge.currentTable || t.fields.length > 1)
        targetBox.currentIndex = targets.length > 0 ? 0 : -1
        showBox.currentIndex = 0
        missing = []
        error = ""
        open()
    }

    function go(addMissing) {
        if (targets.length === 0) { error = "There is no other table to point at yet."; return }
        const r = Bridge.makeLookup(field.name, targets[targetBox.currentIndex].name, showBox.currentValue, addMissing)
        if (r.ok) { close(); fieldsDialog.openFor(); return }
        missing = r.missing || []
        error = r.error
    }

    title: "Point " + (field.label || "") + " at another table"
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: 520
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 8
        Label {
            Layout.fillWidth: true
            text: "Each " + (dialog.field.label || "") + " becomes the row of the other table with the same words. "
                + "Change a name there and it changes here too."
            wrapMode: Text.WordWrap
        }
        GridLayout {
            columns: 2
            columnSpacing: 10
            rowSpacing: 6
            Layout.topMargin: 6
            Label { text: "Points at" }
            ComboBox {
                id: targetBox
                objectName: "makeLookupTarget"
                Layout.preferredWidth: 260
                model: dialog.targets
                textRole: "name"
                onActivated: { showBox.currentIndex = 0; dialog.missing = []; dialog.error = "" }
            }
            Label { text: "Matched by" }
            ComboBox {
                id: showBox
                objectName: "makeLookupShow"
                Layout.preferredWidth: 260
                model: dialog.targetFields
                textRole: "label"
                valueRole: "name"
                onActivated: { dialog.missing = []; dialog.error = "" }
            }
        }
        Label {
            Layout.fillWidth: true
            visible: dialog.error !== ""
            text: dialog.error
            color: dialog.missing.length > 0 ? Theme.yellow : Theme.red
            wrapMode: Text.WordWrap
        }
    }

    footer: DialogButtonBox {
        ActionButton { text: "Cancel"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        ActionButton {
            visible: dialog.missing.length > 0
            objectName: "makeLookupAddMissing"
            text: "Add " + (dialog.missing.length === 1 ? "it" : "all " + dialog.missing.length) + " to " + targetBox.currentText + " and go on"
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: dialog.go(true)
        }
        ActionButton {
            visible: dialog.missing.length === 0
            text: "Make it a lookup"
            objectName: "makeLookupGo"
            primary: true
            enabled: dialog.targets.length > 0 && showBox.currentIndex >= 0
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: dialog.go(false)
        }
    }
    onRejected: fieldsDialog.openFor()
}
