import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// "Show rows where  [Field]  [is / is more than / contains / …]  [value]  ×    Apply  Clear  + Rule   Views…"
//              "and [Field]  [...]  [value]  ×"
// The rule is positive on purpose: to hide people who moved, say "Moved is not Yes".
// Several rules match all of them ("and") or any of them ("or"); the matches on offer
// follow the field's type, so a date reads "is after" and a number "is more than".
// A rule worth keeping is saved as a view (Views… → Save view…) inside the database file,
// together with the sort picked by tapping a column heading.
RowLayout {
    id: bar
    objectName: "filterBar"
    spacing: 8
    property string match: "all"
    // Which table the bar was last showing, so moving to another table starts it fresh.
    property string shownTable: ""

    ListModel { id: ruleModel; objectName: "ruleModel" }

    function fieldAt(name) {
        for (let i = 0; i < Bridge.fields.length; i++) if (Bridge.fields[i].name === name) return Bridge.fields[i]
        return null
    }
    function blankRule() {
        const first = Bridge.fields[0]
        return { field: first ? first.name : "", op: "is", value: "" }
    }
    // Fill the rows in place (rows that stay keep their boxes), then trim or add at the end.
    function loadRules(list) {
        while (ruleModel.count > list.length) ruleModel.remove(ruleModel.count - 1)
        for (let i = 0; i < list.length; i++) {
            if (i < ruleModel.count) ruleModel.set(i, list[i])
            else ruleModel.append(list[i])
        }
    }
    function resetRules() {
        loadRules([blankRule()])
        match = "all"
    }
    function needsValue(op) {
        return !(op === "empty" || op === "not_empty")
    }
    function rules() {
        const out = []
        for (let i = 0; i < ruleModel.count; i++) {
            const r = ruleModel.get(i)
            out.push({ field: r.field, op: r.op, value: needsValue(r.op) ? r.value : "" })
        }
        return out
    }

    function apply() {
        if (ruleModel.count === 0 || Bridge.fields.length === 0) return
        const r = Bridge.setFilterRules(match, rules())
        if (!r.ok) toast.show(r.error)
    }

    function clear() {
        resetRules()
        const r = Bridge.clearFilter()
        if (!r.ok) toast.show(r.error)
    }

    // What a saved view would keep, in words: "Rows where Moved is not Yes, sorted by Age, highest first".
    function viewWords() {
        const where = Bridge.filterWords !== "" ? "Rows where " + Bridge.filterWords : "All rows"
        return Bridge.sortWords !== "" ? where + ", sorted by " + Bridge.sortWords : where
    }

    function addRule() {
        ruleModel.append(blankRule())
    }

    function removeRule(index) {
        ruleModel.remove(index)
        if (ruleModel.count === 0) resetRules()
        if (Bridge.filterWords !== "") apply()   // a rule taken off an applied filter shows more rows now
    }

    Component.onCompleted: resetRules()

    // When the table (or its filter) changes, show the rules on the bar.
    Connections {
        target: Bridge
        function onTableChanged() {
            const shown = Bridge.filterRules
            const otherTable = Bridge.currentTable !== bar.shownTable
            bar.shownTable = Bridge.currentTable
            if (shown.length > 0) {
                bar.loadRules(shown.map(r => ({ field: r.field, op: r.op,
                                                value: r.value === undefined || r.value === null ? "" : String(r.value) })))
                bar.match = Bridge.filterMatch
            } else if (otherTable) {
                // No rule on the new table: don't carry the last table's rule over.
                bar.resetRules()
            } else {
                // Same table, no filter: keep what was typed, but drop fields that are gone.
                for (let i = 0; i < ruleModel.count; i++)
                    if (!bar.fieldAt(ruleModel.get(i).field)) ruleModel.set(i, bar.blankRule())
            }
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 6

        Repeater {
            model: ruleModel
            delegate: RowLayout {
                id: ruleRow
                required property int index
                required property string field
                required property string op
                required property string value
                property var fieldInfo: bar.fieldAt(field) || { type: "text", label: "" }
                property var ops: Bridge.filterOpsFor(fieldInfo.type)
                Layout.fillWidth: true
                spacing: 8

                // Not a binding: typing (or a script) sets the text, and a new rule from the bridge still shows.
                onValueChanged: if (valueField.text !== value) valueField.text = value

                function opIndex() {
                    for (let j = 0; j < ops.length; j++) if (ops[j].key === op) return j
                    return 0
                }

                Label {
                    visible: ruleRow.index === 0
                    Layout.preferredWidth: 118
                    text: "Show rows where"
                    color: Theme.lightForeground
                }
                ComboBox {
                    visible: ruleRow.index > 0
                    objectName: "matchBox" + ruleRow.index
                    Layout.preferredWidth: 118
                    model: [{ key: "all", label: "and" }, { key: "any", label: "or" }]
                    textRole: "label"
                    currentIndex: bar.match === "any" ? 1 : 0
                    onActivated: function(i) { bar.match = i === 1 ? "any" : "all" }
                }
                ComboBox {
                    id: fieldBox
                    objectName: ruleRow.index === 0 ? "filterField" : "filterField" + ruleRow.index
                    Layout.preferredWidth: 160
                    model: Bridge.fields
                    textRole: "label"
                    currentIndex: {
                        for (let i = 0; i < Bridge.fields.length; i++) if (Bridge.fields[i].name === ruleRow.field) return i
                        return 0
                    }
                    onActivated: function(i) {
                        const chosen = Bridge.fields[i]
                        if (!chosen) return
                        ruleModel.setProperty(ruleRow.index, "field", chosen.name)
                        // A match that does not fit the new field's type goes back to "is".
                        const fits = Bridge.filterOpsFor(chosen.type).some(o => o.key === ruleRow.op)
                        if (!fits) ruleModel.setProperty(ruleRow.index, "op", "is")
                        valueField.forceActiveFocus()
                    }
                }
                ComboBox {
                    id: opBox
                    objectName: ruleRow.index === 0 ? "filterOp" : "filterOp" + ruleRow.index
                    Layout.preferredWidth: 150
                    model: ruleRow.ops
                    textRole: "label"
                    currentIndex: ruleRow.opIndex()
                    onActivated: function(i) {
                        const chosen = ruleRow.ops[i]
                        ruleModel.setProperty(ruleRow.index, "op", chosen.key)
                        if (!chosen.needsValue && ruleModel.count === 1) bar.apply()
                        else valueField.forceActiveFocus()
                    }
                }
                TextField {
                    id: valueField
                    objectName: ruleRow.index === 0 ? "filterValue" : "filterValue" + ruleRow.index
                    Layout.fillWidth: true
                    Layout.minimumWidth: 90
                    Layout.maximumWidth: 220
                    visible: bar.needsValue(ruleRow.op)
                    Component.onCompleted: text = ruleRow.value
                    placeholderText: ruleRow.fieldInfo.type === "boolean" ? "yes or no"
                                   : ruleRow.fieldInfo.type === "date" ? "like 2024-01-31" : "a value"
                    onTextEdited: ruleModel.setProperty(ruleRow.index, "value", text)
                    onAccepted: bar.apply()
                }
                // Keeps the remove buttons in line when a row has no value box.
                Item { visible: !valueField.visible; Layout.fillWidth: true; Layout.maximumWidth: 220 }
                ToolButton {
                    text: "\u00d7"
                    objectName: "removeRule" + ruleRow.index
                    visible: ruleModel.count > 1
                    font.pointSize: 13
                    ToolTip.visible: hovered
                    ToolTip.text: "Take this rule off"
                    onClicked: bar.removeRule(ruleRow.index)
                }
            }
        }
    }

    ActionButton { Layout.alignment: Qt.AlignTop; text: "Apply"; primary: true; onClicked: bar.apply() }
    ActionButton { Layout.alignment: Qt.AlignTop; text: "Clear"; visible: Bridge.filterWords !== ""; onClicked: bar.clear() }
    ActionButton {
        Layout.alignment: Qt.AlignTop
        objectName: "addRuleButton"
        text: "+ Rule"
        enabled: ruleModel.count < 10
        onClicked: bar.addRule()
    }
    Item { Layout.fillWidth: true; Layout.minimumWidth: 0 }

    // ---- saved views ----------------------------------------------------------
    ActionButton {
        Layout.alignment: Qt.AlignTop
        text: Bridge.currentView !== "" ? "View: " + Bridge.currentView : "Views…"
        objectName: "viewsButton"
        onClicked: viewsMenu.open()
        Menu {
            id: viewsMenu
            objectName: "viewsMenu"
            // The button sits at the right edge: open leftwards, wide enough for "Name · rule".
            x: parent.width - width
            y: parent.height
            onAboutToShow: {
                let w = 240
                for (let i = 0; i < count; i++) {
                    const item = itemAt(i)
                    // A menu item's own implicitWidth follows the menu; its label knows the text width.
                    if (item && item.visible && item.contentItem)
                        w = Math.max(w, item.contentItem.implicitWidth + item.leftPadding + item.rightPadding)
                }
                width = Math.min(w + leftPadding + rightPadding, 640)
            }
            MenuItem {
                visible: Bridge.views.length === 0
                height: visible ? implicitHeight : 0
                enabled: false
                text: "No saved views yet — Apply a filter or sort, then Save view…"
            }
            Repeater {
                model: Bridge.views
                MenuItem {
                    required property var modelData
                    text: modelData.name + (modelData.default ? "  (opens with this)" : "") + "  ·  " + modelData.words
                    onTriggered: { const r = Bridge.applyView(modelData.name); if (!r.ok) toast.show(r.error) }
                }
            }
            MenuSeparator {}
            MenuItem {
                text: "Save view…"
                enabled: Bridge.filterWords !== "" || Bridge.sortWords !== ""
                onTriggered: saveViewDialog.openFor()
            }
            MenuItem {
                text: "Rename “" + Bridge.currentView + "”…"
                visible: Bridge.currentView !== ""
                height: visible ? implicitHeight : 0
                onTriggered: renameViewDialog.openFor(Bridge.currentView)
            }
            MenuItem {
                text: "Delete “" + Bridge.currentView + "”…"
                visible: Bridge.currentView !== ""
                height: visible ? implicitHeight : 0
                onTriggered: deleteViewConfirm.ask(Bridge.currentView)
            }
        }
    }

    Dialog {
        id: saveViewDialog
        objectName: "saveViewDialog"
        property string saveError: ""
        function openFor() {
            viewName.text = Bridge.currentView
            defaultBox.checked = false
            for (const v of Bridge.views) if (v.name === Bridge.currentView) defaultBox.checked = v.default
            saveError = ""
            open()
            viewName.forceActiveFocus()
            viewName.selectAll()
        }
        function go(replace) {
            const r = Bridge.saveView(viewName.text.trim(), replace, defaultBox.checked)
            if (r.ok) { close(); return }
            if (r.needsConfirm) { replaceViewConfirm.viewName = r.name; replaceViewConfirm.open(); return }
            saveError = r.error
        }
        title: "Save this view"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 460
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            Label { Layout.fillWidth: true; text: bar.viewWords(); color: Theme.lightForeground; wrapMode: Text.WordWrap }
            Label { text: "Name"; font.bold: true; Layout.topMargin: 6 }
            TextField { id: viewName; Layout.fillWidth: true; placeholderText: "Like “Still here”"; onAccepted: saveViewDialog.go(false) }
            CheckBox { id: defaultBox; text: "Open this table with this view" }
            Label { Layout.fillWidth: true; text: "Saved inside the database file, so it travels with it."; color: Theme.lightForeground; font.pointSize: 10; wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; visible: saveViewDialog.saveError !== ""; text: saveViewDialog.saveError; color: Theme.red; wrapMode: Text.WordWrap }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Cancel"; onClicked: saveViewDialog.reject() }
            ActionButton { text: "Save"; primary: true; enabled: viewName.text.trim() !== ""; onClicked: saveViewDialog.go(false) }
        }
    }

    Dialog {
        id: replaceViewConfirm
        property string viewName: ""
        title: "Replace the view “" + viewName + "”?"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 440
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label { text: "There is already a view with that name. It will now show: " + bar.viewWords() + "."; wrapMode: Text.WordWrap }
        footer: DialogButtonBox {
            ActionButton { text: "Keep the old one"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Replace it"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: saveViewDialog.go(true)
    }

    Dialog {
        id: renameViewDialog
        property string oldName: ""
        property string renameError: ""
        function openFor(name) { oldName = name; newViewName.text = name; renameError = ""; open(); newViewName.forceActiveFocus(); newViewName.selectAll() }
        function go() { const r = Bridge.renameView(oldName, newViewName.text.trim()); if (r.ok) close(); else renameError = r.error }
        title: "Rename the view “" + oldName + "”"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 440
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            TextField { id: newViewName; Layout.fillWidth: true; onAccepted: renameViewDialog.go() }
            Label { Layout.fillWidth: true; visible: renameViewDialog.renameError !== ""; text: renameViewDialog.renameError; color: Theme.red; wrapMode: Text.WordWrap }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Cancel"; onClicked: renameViewDialog.reject() }
            ActionButton { text: "Rename"; primary: true; enabled: newViewName.text.trim() !== ""; onClicked: renameViewDialog.go() }
        }
    }

    Dialog {
        id: deleteViewConfirm
        property string viewName: ""
        function ask(name) { viewName = name; open() }
        title: "Delete the view “" + viewName + "”?"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 440
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label { text: "The rows stay. Only the saved filter goes."; wrapMode: Text.WordWrap }
        footer: DialogButtonBox {
            ActionButton { text: "Keep it"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete the view"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.deleteView(viewName); if (!r.ok) toast.show(r.error) }
    }
}
