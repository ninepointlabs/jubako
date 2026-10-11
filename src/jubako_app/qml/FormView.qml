import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One record at a time. Previous / Next walk the rows; Save writes the one
// on screen; New row starts a blank one; Duplicate starts a new row from the
// one on screen. Yes/no fields are a checkbox, everything else is a box to
// type in. Which fields show, in what order and called what, is the table's
// form (Arrange…).
Item {
    id: form
    property int rowIndex: -1          // which row of the grid is on screen; -1 = new row
    property int rowId: 0              // 0 = not saved yet
    property var edits: ({})           // field name -> value typed so far
    property bool dirty: false
    property bool copied: false        // a new row started from another one
    property string error: ""
    signal deleteRequested(int rowId)

    function load(index) {
        error = ""
        if (index < 0 || index >= Bridge.rows.rowCount()) {
            rowIndex = -1
            rowId = 0
            const blank = {}
            for (const f of Bridge.formFields)
                blank[f.name] = f.type === "boolean" ? false : ""
            edits = blank
        } else {
            const rec = Bridge.rows.record(index)
            rowIndex = index
            rowId = rec.id
            edits = rec.values
        }
        dirty = false
        copied = false
        fieldsRepeater.model = []      // rebuild the editors so they show the new values
        fieldsRepeater.model = Bridge.formFields
    }

    // A new row with the values of the one on screen. No-repeats fields start blank, or it could not be saved.
    function duplicate() {
        if (dirty && !save())
            return
        const next = Object.assign({}, edits)
        const cleared = []
        for (const f of Bridge.fields) {
            if (f.unique && next[f.name] !== undefined && next[f.name] !== "") {
                next[f.name] = ""
                cleared.push(f.label)
            }
        }
        rowIndex = -1
        rowId = 0
        edits = next
        dirty = true
        copied = true
        error = ""
        fieldsRepeater.model = []
        fieldsRepeater.model = Bridge.formFields
        if (cleared.length > 0) toast.show(cleared.join(", ") + (cleared.length === 1 ? " is" : " are") + " left blank: it cannot repeat.")
    }

    function set(name, value) {
        const next = Object.assign({}, edits)
        next[name] = value
        edits = next
        dirty = true
    }

    function save() {
        const r = Bridge.saveRow(rowId, edits)
        if (!r.ok) {
            error = r.error
            return false
        }
        error = ""
        load(r.rowIndex)
        toast.show(rowId > 0 ? "Saved." : "Row added.")
        return true
    }

    function go(delta) {
        if (dirty && !save())
            return
        const count = Bridge.rows.rowCount()
        if (count === 0)
            return
        let next = rowIndex < 0 ? (delta > 0 ? 0 : count - 1) : rowIndex + delta
        next = Math.max(0, Math.min(count - 1, next))
        load(next)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        // ---- where we are ---------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ActionButton { text: "‹ Previous"; enabled: Bridge.rows.rowCount() > 0 && form.rowIndex !== 0; onClicked: form.go(-1) }
            ActionButton { text: "Next ›"; enabled: Bridge.rows.rowCount() > 0 && form.rowIndex < Bridge.rows.rowCount() - 1; onClicked: form.go(1) }
            Label {
                Layout.leftMargin: 8
                objectName: "formWhere"
                text: (Bridge.formTitle !== "" ? Bridge.formTitle + "  \u00b7  " : "")
                    + (form.rowIndex < 0
                       ? (form.copied ? "New row (a copy)" : "New row")
                       : "Row " + (form.rowIndex + 1) + " of " + Bridge.rows.rowCount())
                font.pointSize: 13
                font.bold: true
            }
            Label {
                text: form.dirty ? "• not saved yet" : ""
                color: Theme.yellow
                font.pointSize: 10
            }
            Item { Layout.fillWidth: true }
            ActionButton { text: "Arrange\u2026"; objectName: "formArrange"; onClicked: formDesignDialog.openFor() }
            ActionButton {
                text: "Duplicate"
                objectName: "formDuplicate"
                enabled: form.rowId > 0 && Bridge.canEdit
                onClicked: form.duplicate()
            }
            ActionButton { text: "New row"; onClicked: { if (!form.dirty || form.save()) form.load(-1) } }
        }

        // ---- the fields -----------------------------------------------------
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            GridLayout {
                width: parent.width
                columns: 2
                columnSpacing: 16
                rowSpacing: 12

                Repeater {
                    id: fieldsRepeater
                    model: Bridge.formFields

                    delegate: Item {
                        id: cell
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.columnSpan: 2
                        implicitHeight: rowLayout.implicitHeight

                        RowLayout {
                            id: rowLayout
                            width: parent.width
                            spacing: 16
                            Label {
                                Layout.preferredWidth: 180
                                Layout.alignment: Qt.AlignVCenter
                                text: cell.modelData.label
                                font.pointSize: 12
                                elide: Text.ElideRight
                            }
                            CheckBox {
                                // Fill the row so the box lines up with the text fields, not mid-row.
                                Layout.fillWidth: true
                                visible: cell.modelData.type === "boolean"
                                checked: visible && form.edits[cell.modelData.name] === true
                                text: checked ? "Yes" : "No"
                                onToggled: form.set(cell.modelData.name, checked)
                            }
                            TextField {
                                Layout.fillWidth: true
                                visible: cell.modelData.type !== "boolean"
                                text: visible ? String(form.edits[cell.modelData.name] ?? "") : ""
                                font.pointSize: 12
                                placeholderText: {
                                    switch (cell.modelData.type) {
                                    case "integer": return "A whole number, like 12"
                                    case "real": return "A number, like 12.5"
                                    case "date": return "A date, like 2024-01-31"
                                    default: return ""
                                    }
                                }
                                inputMethodHints: (cell.modelData.type === "integer" || cell.modelData.type === "real")
                                    ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
                                onTextEdited: form.set(cell.modelData.name, text)
                                onAccepted: form.save()
                            }
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: form.error !== ""
            text: form.error
            color: Theme.red
            wrapMode: Text.WordWrap
        }

        // ---- save / delete ----------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ActionButton {
                text: form.rowId > 0 ? "Save" : "Add this row"
                primary: true
                enabled: form.dirty || form.rowId === 0
                onClicked: form.save()
            }
            ActionButton {
                text: "Undo changes"
                visible: form.dirty
                onClicked: form.load(form.rowIndex)
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                text: "Delete this row"
                visible: form.rowId > 0
                onClicked: form.deleteRequested(form.rowId)
            }
        }
    }
}
