import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Report designer lite: pick columns, a title, the page; which rows and in what
// order, groups and totals; see it; print it or save a PDF. The preview is the
// real thing — the same pages that print.
Dialog {
    id: dialog
    objectName: "reportDialog"
    property string table: ""
    property var allFields: []          // [{name, label, type}]
    property var picked: []             // field names in order
    property int page: 0
    property bool ready: false

    property var rowFilter: ({})        // the table's filter when the dialog opened, or {}
    property bool hasFilter: !!(rowFilter.field || (rowFilter.rules && rowFilter.rules.length))
    property string viewName: ""        // a saved view to take rows from, or ""
    property var viewList: []           // [{name, words}] for this table
    property string sortField: ""       // "" means the order rows were added
    property bool sortDesc: false
    property string groupBy: ""
    property var totals: ({})           // {field: "sum" | "average"}

    function fieldInfo(name) {
        for (const f of allFields) if (f.name === name) return f
        return null
    }
    function directionWords(type) {
        if (type === "text") return ["A to Z", "Z to A"]
        if (type === "date") return ["oldest first", "newest first"]
        if (type === "boolean") return ["No first", "Yes first"]
        return ["lowest first", "highest first"]
    }
    function numberColumns() {
        return allFields.filter(f => (f.type === "integer" || f.type === "real") && picked.indexOf(f.name) >= 0)
    }
    function setTotal(name, how) {
        const next = Object.assign({}, totals)
        if (how) next[name] = how
        else delete next[name]
        totals = next
        touched()
    }
    function filterFromBridge() {
        const rules = Bridge.filterRules
        if (rules.length === 0) return {}
        if (rules.length === 1) return rules[0]
        return { match: Bridge.filterMatch, rules: rules }
    }

    function openFor(theTable, fields) {
        table = theTable
        allFields = fields
        picked = fields.map(f => f.name)
        rowFilter = filterFromBridge()
        filterBox.checked = hasFilter
        viewList = Report.viewsFor(theTable)
        // A table showing a saved view untouched prints from that view, so the report follows it.
        viewName = Bridge.currentView
        sortField = Bridge.sort.length > 0 ? Bridge.sort[0].field : ""
        sortDesc = Bridge.sort.length > 0 ? Bridge.sort[0].descending : false
        groupBy = ""
        totals = ({})
        countBox.checked = false
        headerField.text = ""
        footerField.text = ""
        titleField.text = theTable.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())
        nameField.text = ""
        sizeBox.currentIndex = 0
        landscapeBox.checked = false
        fitBox.checked = true
        numbersBox.checked = false
        marginsBox.value = 15
        fontBox.value = 10
        page = 0
        ready = true
        rebuild()
        open()
    }

    function loadKept(name) {
        const r = Report.load(name)
        if (!r.ok) { toast.show(r.error); return }
        const s = r.spec
        table = s.table
        picked = s.columns
        rowFilter = s.filter ? s.filter : {}
        filterBox.checked = hasFilter
        viewList = Report.viewsFor(s.table)
        viewName = s.view || ""
        sortField = s.sort && s.sort.length > 0 ? s.sort[0].field : ""
        sortDesc = s.sort && s.sort.length > 0 ? s.sort[0].descending : false
        groupBy = s.group_by || ""
        totals = s.totals || ({})
        countBox.checked = !!s.show_count
        headerField.text = s.header_text || ""
        footerField.text = s.footer_text || ""
        titleField.text = s.title
        nameField.text = s.name
        sizeBox.currentIndex = Math.max(0, Report.pageSizes().indexOf(s.page_size))
        landscapeBox.checked = s.orientation === "landscape"
        fitBox.checked = s.fit_to_width
        numbersBox.checked = s.show_row_numbers
        marginsBox.value = s.margins_mm
        fontBox.value = s.font_pt
        page = 0
        preview.source = Report.previewSource(0)
    }

    function currentSpec() {
        return {
            "table": table,
            "title": titleField.text,
            "columns": picked,
            "page_size": Report.pageSizes()[sizeBox.currentIndex],
            "orientation": landscapeBox.checked ? "landscape" : "portrait",
            "margins_mm": marginsBox.value,
            "fit_to_width": fitBox.checked,
            "font_pt": fontBox.value,
            "show_row_numbers": numbersBox.checked,
            "view": viewName,
            "filter": !viewName && filterBox.checked && hasFilter ? rowFilter : null,
            "sort": !viewName && sortField ? [{ "field": sortField, "descending": sortDesc }] : [],
            "group_by": groupBy,
            "totals": totals,
            "show_count": countBox.checked,
            "header_text": headerField.text,
            "footer_text": footerField.text,
            "name": nameField.text
        }
    }

    function rebuild() {
        if (!ready) return
        const r = Report.build(currentSpec())
        if (r.ok) {
            page = Math.min(page, Math.max(0, r.pages - 1))
            preview.source = Report.previewSource(page)
        }
    }

    // Any change waits a moment, then relays out the whole report.
    Timer { id: settle; interval: 250; onTriggered: dialog.rebuild() }
    function touched() { settle.restart() }

    function toggle(name, on) {
        let next = picked.filter(n => n !== name)
        if (on) {
            // keep table order
            next = allFields.map(f => f.name).filter(n => n === name || next.indexOf(n) >= 0)
        }
        picked = next
        touched()
    }

    title: "Print " + (table || "a table")
    modal: true
    anchors.centerIn: parent
    width: Math.min(parent.width - 40, 1180)
    height: Math.min(parent.height - 40, 780)
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: RowLayout {
        spacing: 20

        // ---- settings -------------------------------------------------------
        ScrollView {
            Layout.preferredWidth: 340
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth

            ColumnLayout {
                width: parent.width
                spacing: 10

                Label { text: "Title"; font.bold: true }
                TextField { id: titleField; Layout.fillWidth: true; onTextEdited: dialog.touched() }

                Label { text: "Columns"; font.bold: true; Layout.topMargin: 6 }
                Repeater {
                    model: dialog.allFields
                    delegate: CheckBox {
                        required property var modelData
                        text: modelData.label
                        checked: dialog.picked.indexOf(modelData.name) >= 0
                        onToggled: dialog.toggle(modelData.name, checked)
                    }
                }

                Label { text: "Rows"; font.bold: true; Layout.topMargin: 6 }
                RowLayout {
                    visible: dialog.viewList.length > 0
                    Label { text: "From a saved view" }
                    ComboBox {
                        id: viewBox
                        objectName: "reportViewBox"
                        Layout.fillWidth: true
                        model: ["None"].concat(dialog.viewList.map(v => v.name))
                        currentIndex: Math.max(0, dialog.viewList.findIndex(v => v.name === dialog.viewName) + 1)
                        onActivated: function(i) { dialog.viewName = i === 0 ? "" : dialog.viewList[i - 1].name; dialog.touched() }
                    }
                }
                Label {
                    visible: dialog.viewName !== ""
                    Layout.fillWidth: true
                    text: {
                        const v = dialog.viewList.find(v => v.name === dialog.viewName)
                        return (v ? v.words : "") + "\nThe report follows the view when the view changes."
                    }
                    color: Theme.lightForeground
                    font.pointSize: 10
                    wrapMode: Text.WordWrap
                }
                CheckBox {
                    id: filterBox
                    visible: dialog.hasFilter && dialog.viewName === ""
                    Layout.fillWidth: true
                    text: "Only rows where " + (Report.spec.filter_words || Bridge.filterWords || "")
                    onToggled: dialog.touched()
                    contentItem: Label {
                        leftPadding: filterBox.indicator.width + filterBox.spacing
                        text: filterBox.text
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                Label {
                    visible: !dialog.hasFilter && dialog.viewName === ""
                    Layout.fillWidth: true
                    text: "Every row. To print only some, filter the table first (Show rows where\u2026) and open this again."
                    color: Theme.lightForeground
                    font.pointSize: 10
                    wrapMode: Text.WordWrap
                }

                Label { text: "Order"; font.bold: true; Layout.topMargin: 6; visible: dialog.viewName === "" }
                RowLayout {
                    visible: dialog.viewName === ""
                    ComboBox {
                        id: sortBox
                        objectName: "reportSortBox"
                        Layout.fillWidth: true
                        model: ["As the rows were added"].concat(dialog.allFields.map(f => f.label))
                        currentIndex: Math.max(0, dialog.allFields.findIndex(f => f.name === dialog.sortField) + 1)
                        onActivated: function(i) { dialog.sortField = i === 0 ? "" : dialog.allFields[i - 1].name; dialog.touched() }
                    }
                    ComboBox {
                        Layout.preferredWidth: 130
                        visible: dialog.sortField !== ""
                        model: dialog.directionWords((dialog.fieldInfo(dialog.sortField) || {}).type)
                        currentIndex: dialog.sortDesc ? 1 : 0
                        onActivated: function(i) { dialog.sortDesc = i === 1; dialog.touched() }
                    }
                }

                Label { text: "Groups"; font.bold: true; Layout.topMargin: 6 }
                ComboBox {
                    id: groupBox
                    objectName: "reportGroupBox"
                    Layout.fillWidth: true
                    model: ["No groups"].concat(dialog.allFields.map(f => "A heading for each " + f.label))
                    currentIndex: Math.max(0, dialog.allFields.findIndex(f => f.name === dialog.groupBy) + 1)
                    onActivated: function(i) {
                        const was = dialog.groupBy
                        dialog.groupBy = i === 0 ? "" : dialog.allFields[i - 1].name
                        if (!was && dialog.groupBy) countBox.checked = true
                        dialog.touched()
                    }
                }

                Label { text: "Totals"; font.bold: true; Layout.topMargin: 6 }
                CheckBox { id: countBox; objectName: "reportCountBox"; text: "Say how many rows"; onToggled: dialog.touched() }
                Repeater {
                    model: dialog.numberColumns()
                    delegate: RowLayout {
                        required property var modelData
                        Label { text: modelData.label; Layout.fillWidth: true; elide: Text.ElideRight }
                        ComboBox {
                            Layout.preferredWidth: 130
                            model: ["No total", "Sum", "Average"]
                            currentIndex: dialog.totals[modelData.name] === "sum" ? 1 : dialog.totals[modelData.name] === "average" ? 2 : 0
                            onActivated: function(i) { dialog.setTotal(modelData.name, ["", "sum", "average"][i]) }
                        }
                    }
                }
                Label {
                    visible: dialog.numberColumns().length === 0
                    Layout.fillWidth: true
                    text: "Number columns can show a sum or an average. This report has none."
                    color: Theme.lightForeground
                    font.pointSize: 10
                    wrapMode: Text.WordWrap
                }

                Label { text: "Page"; font.bold: true; Layout.topMargin: 6 }
                RowLayout {
                    ComboBox {
                        id: sizeBox
                        Layout.preferredWidth: 130
                        model: ["Letter", "A4", "Legal"]
                        onActivated: dialog.touched()
                    }
                    CheckBox { id: landscapeBox; text: "Sideways (landscape)"; onToggled: dialog.touched() }
                }
                CheckBox { id: fitBox; text: "Fit the table to the page width"; onToggled: dialog.touched() }
                CheckBox { id: numbersBox; text: "Number the rows"; onToggled: dialog.touched() }
                RowLayout {
                    Label { text: "Margins (mm)" }
                    SpinBox { id: marginsBox; from: 5; to: 40; value: 15; onValueModified: dialog.touched() }
                }
                RowLayout {
                    Label { text: "Text size" }
                    SpinBox { id: fontBox; from: 6; to: 16; value: 10; onValueModified: dialog.touched() }
                }
                Label { text: "Top of every page"; font.bold: true; Layout.topMargin: 6 }
                TextField { id: headerField; objectName: "reportHeader"; Layout.fillWidth: true; placeholderText: "Optional, like your shop's name"; onTextEdited: dialog.touched() }
                Label { text: "Foot of every page"; font.bold: true }
                TextField { id: footerField; objectName: "reportFooter"; Layout.fillWidth: true; placeholderText: "Optional; the title is used when blank"; onTextEdited: dialog.touched() }

                Label { text: "Keep this report"; font.bold: true; Layout.topMargin: 6 }
                RowLayout {
                    TextField { id: nameField; Layout.fillWidth: true; placeholderText: "A name, like Monthly list" }
                    ActionButton {
                        text: "Keep"
                        enabled: nameField.text.trim() !== ""
                        onClicked: { dialog.rebuild(); const r = Report.keep(nameField.text.trim()); if (!r.ok) toast.show(r.error); keptRepeater.model = Report.kept() }
                    }
                }
                Repeater {
                    id: keptRepeater
                    model: Report.kept()
                    delegate: ItemDelegate {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.name + "  ·  " + modelData.table
                        onClicked: dialog.loadKept(modelData.name)
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: Report.error !== ""
                    text: Report.error
                    color: Theme.red
                    wrapMode: Text.WordWrap
                }
            }
        }

        // ---- preview -----------------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                ActionButton { text: "‹"; enabled: dialog.page > 0; onClicked: { dialog.page--; preview.source = Report.previewSource(dialog.page) } }
                ActionButton { text: "›"; enabled: dialog.page < Report.pageCount - 1; onClicked: { dialog.page++; preview.source = Report.previewSource(dialog.page) } }
                Label {
                    text: Report.pageCount > 0
                        ? "Page " + (dialog.page + 1) + " of " + Report.pageCount + "  ·  " + Report.rowCount + " rows"
                        : ""
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: Theme.isDark ? Theme.darkerBackground : Theme.lighterBackground
                radius: 6
                clip: true
                Image {
                    id: preview
                    anchors.fill: parent
                    anchors.margins: 12
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    cache: false
                    sourceSize.width: 1000
                }
            }
        }
    }

    footer: DialogButtonBox {
        ActionButton { text: "Close"; onClicked: dialog.close() }
        ActionButton {
            text: "Save PDF…"
            enabled: Report.pageCount > 0
            onClicked: { dialog.rebuild(); pdfDialog.selectedFile = Bridge.documentsFolder() + "/" + (titleField.text || table).replace(/[\/\\]/g, "-") + ".pdf"; pdfDialog.open() }
        }
        ActionButton {
            text: "Print…"
            primary: true
            enabled: Report.pageCount > 0
            onClicked: { dialog.rebuild(); const r = Report.printReport(); if (!r.ok && !r.cancelled) toast.show(r.error) }
        }
    }
}
