import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Arrange the form: its title, the order of its fields, what each is called on
// the form, and which fields it leaves out. A hidden field keeps its values in
// the table; it is only off the form.
Dialog {
    id: dialog
    objectName: "formDesignDialog"
    property string error: ""

    ListModel { id: itemsModel }

    function openFor() {
        const design = Bridge.formDesign()
        titleBox.text = design.title
        itemsModel.clear()
        for (const item of design.items)
            itemsModel.append({ name: item.name, label: item.label, defaultLabel: item.defaultLabel,
                                type: item.type, shown: item.shown })
        error = ""
        open()
    }

    function move(index, delta) {
        const to = index + delta
        if (to < 0 || to >= itemsModel.count) return
        itemsModel.move(index, to, 1)
    }

    function shownCount() {
        let n = 0
        for (let i = 0; i < itemsModel.count; i++) if (itemsModel.get(i).shown) n++
        return n
    }

    function go() {
        const items = []
        for (let i = 0; i < itemsModel.count; i++) {
            const it = itemsModel.get(i)
            items.push({ name: it.name, label: it.label, shown: it.shown })
        }
        const r = Bridge.saveFormDesign(titleBox.text.trim(), items)
        if (r.ok) close(); else error = r.error
    }

    function typeWord(kind) {
        for (const t of Bridge.fieldTypes()) if (t.key === kind) return t.label
        return kind
    }

    title: "Arrange the form for " + Bridge.currentTable
    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(parent.width - 40, 720)
    height: Math.min(parent.height - 40, 640)
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 10
        Label { text: "Title"; font.bold: true }
        TextField { id: titleBox; objectName: "formTitleBox"; Layout.fillWidth: true; placeholderText: "Like Contact, or Stock item" }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 8
            Label { Layout.preferredWidth: 76; text: "Order"; font.bold: true; color: Theme.lightForeground }
            Label { Layout.preferredWidth: 60; text: "Show"; font.bold: true; color: Theme.lightForeground }
            Label { Layout.fillWidth: true; text: "Called on the form"; font.bold: true; color: Theme.lightForeground }
            Label { Layout.preferredWidth: 130; text: "Type"; font.bold: true; color: Theme.lightForeground }
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
                    model: itemsModel
                    delegate: RowLayout {
                        id: itemRow
                        required property int index
                        required property string name
                        required property string label
                        required property string defaultLabel
                        required property string type
                        required property bool shown
                        Layout.fillWidth: true
                        spacing: 8
                        ToolButton {
                            text: "↑"
                            objectName: "formUp_" + itemRow.name
                            enabled: itemRow.index > 0
                            onClicked: dialog.move(itemRow.index, -1)
                        }
                        ToolButton {
                            text: "↓"
                            objectName: "formDown_" + itemRow.name
                            enabled: itemRow.index < itemsModel.count - 1
                            onClicked: dialog.move(itemRow.index, 1)
                        }
                        Item {
                            Layout.preferredWidth: 60
                            implicitHeight: showBox.implicitHeight
                            CheckBox {
                                id: showBox
                                objectName: "formShow_" + itemRow.name
                                checked: itemRow.shown
                                onToggled: itemsModel.setProperty(itemRow.index, "shown", checked)
                            }
                        }
                        TextField {
                            Layout.fillWidth: true
                            objectName: "formLabel_" + itemRow.name
                            text: itemRow.label
                            placeholderText: itemRow.defaultLabel
                            opacity: itemRow.shown ? 1 : 0.5
                            onTextEdited: itemsModel.setProperty(itemRow.index, "label", text)
                        }
                        Label {
                            Layout.preferredWidth: 130
                            text: dialog.typeWord(itemRow.type)
                            color: Theme.lightForeground
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: "A field that is not shown keeps its values in the table; it is only off the form. New fields go on the end."
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
            text: "Back to the plain form"
            onClicked: { const r = Bridge.resetFormDesign(); if (r.ok) dialog.close(); else dialog.error = r.error }
        }
        ActionButton { text: "Cancel"; onClicked: dialog.reject() }
        ActionButton { text: "Keep it"; objectName: "formDesignGo"; primary: true; onClicked: dialog.go() }
    }
}
