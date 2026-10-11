import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The fields of the open table: add one, rename one, delete one, say whether its
// values may repeat. Every row shows the label people see, the name inside the
// database, and the type.
// Add / Rename / Delete each close this list and open their own dialog at
// page level, then bring the list back, because a dialog inside a modal
// dialog does not show reliably in Qt Quick.
Dialog {
    id: dialog
    objectName: "fieldsDialog"
    property string error: ""

    function openFor() { error = ""; open() }

    function typeWord(kind) {
        const types = Bridge.fieldTypes()
        for (const t of types) if (t.key === kind) return t.label
        return kind
    }

    title: "Fields of " + Bridge.currentTable
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent.width - 40, 940)
    height: Math.min(parent.height - 40, 600)
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 10

        // ---- the one thing most people come here for -------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            ActionButton {
                text: "Add field…"
                objectName: "fieldsAddButton"
                primary: true
                onClicked: { dialog.close(); addFieldDialog.openFor(true) }
            }
            Label {
                Layout.fillWidth: true
                text: "A new column, like Moved (yes / no). Rows already there start blank."
                color: Theme.lightForeground
                wrapMode: Text.WordWrap
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 12
            Label { Layout.preferredWidth: 170; text: "Label"; font.bold: true; color: Theme.lightForeground; elide: Text.ElideRight }
            Label { Layout.preferredWidth: 150; text: "Name inside"; font.bold: true; color: Theme.lightForeground; elide: Text.ElideRight }
            Label { Layout.preferredWidth: 120; text: "Type"; font.bold: true; color: Theme.lightForeground; elide: Text.ElideRight }
            Label { Layout.preferredWidth: 96; text: "No repeats"; font.bold: true; color: Theme.lightForeground; elide: Text.ElideRight }
            Item { Layout.fillWidth: true }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 4
                Repeater {
                    model: Bridge.fields
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 12
                        Label { Layout.preferredWidth: 170; Layout.maximumWidth: 170; text: modelData.label; elide: Text.ElideRight; font.pointSize: 12 }
                        Label { Layout.preferredWidth: 150; Layout.maximumWidth: 150; text: modelData.name; elide: Text.ElideRight; font.family: Theme.monoFont; color: Theme.lightForeground }
                        Label { Layout.preferredWidth: 120; Layout.maximumWidth: 120; text: dialog.typeWord(modelData.type); elide: Text.ElideRight; color: Theme.lightForeground }
                        Item {
                            Layout.preferredWidth: 96
                            implicitHeight: uniqueBox.implicitHeight
                            CheckBox {
                                id: uniqueBox
                                objectName: "unique_" + modelData.name
                                visible: modelData.type !== "boolean"
                                checked: !!modelData.unique
                                ToolTip.visible: hovered
                                ToolTip.text: "No two rows may have the same " + modelData.label + ". Blanks may."
                                onToggled: {
                                    const r = Bridge.setUnique(modelData.name, checked)
                                    dialog.error = r.ok ? "" : r.error
                                    if (!r.ok) checked = !checked
                                }
                            }
                        }
                        Item { Layout.fillWidth: true }
                        ActionButton { text: "Rename…"; onClicked: { dialog.close(); renameFieldDialog.openFor(modelData) } }
                        ActionButton { text: "Delete…"; enabled: Bridge.fields.length > 1; onClicked: { dialog.close(); deleteFieldConfirm.ask(modelData) } }
                    }
                }
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
        ActionButton { text: "Done"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
    }
}
