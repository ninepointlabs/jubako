import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Doing something with every row on screen at once: the rows the filter shows,
// or every row when no filter is on. Change a field in all of them, delete all
// of them, or see what they add up to. The two that change things say how
// many rows first.
Item {
    id: matching
    // "the 12 rows where Moved is Yes", or "all 40 rows"
    function rowsWords() {
        const n = Bridge.totalRows
        if (Bridge.filterWords !== "")
            return (n === 1 ? "the 1 row" : "the " + n + " rows") + " where " + Bridge.filterWords
        return n === 1 ? "the 1 row" : "all " + n + " rows"
    }
    function countWords() { return Bridge.totalRows === 1 ? "1 row" : Bridge.totalRows + " rows" }

    function openChange() { changeDialog.openFor() }
    function openDelete() { deleteDialog.open() }
    function openSummary() { summaryDialog.openFor() }

    Dialog {
        id: changeDialog
        objectName: "changeRowsDialog"
        property string error: ""
        property var field: Bridge.fields[fieldBox.currentIndex] || ({ type: "text", label: "" })
        function openFor() {
            fieldBox.currentIndex = 0
            valueBox.text = ""
            yesNoBox.currentIndex = 0
            blankBox.checked = false
            error = ""
            open()
        }
        function go() {
            const value = field.type === "boolean" ? (yesNoBox.currentIndex === 0 ? "yes" : "no") : valueBox.text
            const r = Bridge.changeMatching(field.name, value, blankBox.checked)
            if (r.ok) close(); else error = r.error
        }
        title: "Change a field in " + matching.countWords()
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 500
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            Label { Layout.fillWidth: true; text: "In " + matching.rowsWords() + ":"; color: Theme.lightForeground; wrapMode: Text.WordWrap }
            RowLayout {
                spacing: 8
                Label { text: "Set" }
                ComboBox { id: fieldBox; objectName: "changeField"; Layout.preferredWidth: 180; model: Bridge.fields; textRole: "label" }
                Label { text: "to" }
                TextField {
                    id: valueBox
                    objectName: "changeValue"
                    Layout.fillWidth: true
                    visible: changeDialog.field.type !== "boolean"
                    enabled: !blankBox.checked
                    placeholderText: changeDialog.field.type === "date" ? "like 2024-01-31" : "the new value"
                    onAccepted: changeDialog.go()
                }
                ComboBox { id: yesNoBox; visible: changeDialog.field.type === "boolean"; enabled: !blankBox.checked; model: ["Yes", "No"] }
            }
            CheckBox { id: blankBox; objectName: "changeBlank"; text: "Make it blank instead" }
            Label {
                Layout.fillWidth: true
                text: "Every one of those rows gets the new value. This cannot be undone."
                color: Theme.yellow
                wrapMode: Text.WordWrap
            }
            Label { Layout.fillWidth: true; visible: changeDialog.error !== ""; text: changeDialog.error; color: Theme.red; wrapMode: Text.WordWrap }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Cancel"; onClicked: changeDialog.reject() }
            ActionButton { text: "Change " + matching.countWords(); objectName: "changeGo"; primary: true; onClicked: changeDialog.go() }
        }
    }

    Dialog {
        id: deleteDialog
        objectName: "deleteRowsDialog"
        title: "Delete " + matching.countWords() + "?"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 480
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            Label { Layout.fillWidth: true; text: "This deletes " + matching.rowsWords() + "."; wrapMode: Text.WordWrap }
            Label {
                Layout.fillWidth: true
                text: Bridge.filterWords === "" ? "No filter is on: that is every row in the table. This cannot be undone."
                                                : "The other rows stay. This cannot be undone."
                color: Theme.red
                wrapMode: Text.WordWrap
            }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Keep them"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete " + matching.countWords(); primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.deleteMatching(); if (!r.ok) toast.show(r.error) }
    }

    Dialog {
        id: summaryDialog
        objectName: "summaryDialog"
        property var totals: ({ rows: 0, fields: [] })
        function openFor() {
            const r = Bridge.summary()
            if (!r.ok) { toast.show(r.error); return }
            totals = r
            open()
        }
        function line(item) {
            const filled = item.filled === summaryDialog.totals.rows ? "all filled in" : item.filled + " filled in"
            if (item.total !== undefined && item.total !== null)
                return "total " + item.total + "  ·  average " + item.average + "  ·  lowest " + item.lowest + "  ·  highest " + item.highest
            if (item.earliest)
                return "earliest " + item.earliest + "  ·  latest " + item.latest
            if (item.yes !== undefined)
                return item.yes + " Yes, " + (summaryDialog.totals.rows - item.yes) + " No or blank"
            return filled
        }
        title: "What " + matching.countWords() + " add up to"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 680)
        height: Math.min(parent.height - 40, 560)
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            Label { Layout.fillWidth: true; text: matching.rowsWords().charAt(0).toUpperCase() + matching.rowsWords().slice(1) + "."; color: Theme.lightForeground; wrapMode: Text.WordWrap }
            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 6
                    Repeater {
                        model: summaryDialog.totals.fields
                        delegate: RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 12
                            Label { Layout.preferredWidth: 160; text: modelData.label; font.bold: true; elide: Text.ElideRight }
                            Label { Layout.fillWidth: true; text: summaryDialog.line(modelData); wrapMode: Text.WordWrap }
                        }
                    }
                }
            }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Done"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
    }
}
