import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

// One open database: its tables down the left, the rows of one table on the right.
Page {
    id: page
    objectName: "databasePage"
    property string mode: "grid"       // "grid" or "form"
    property int selectedRow: grid.currentRow
    // An empty table in the grid: the toolbar stays, and the space for rows says what to do.
    readonly property bool noRows: Bridge.currentTable !== "" && Bridge.totalRows === 0
                                   && Bridge.filterWords === "" && mode === "grid"
    background: Rectangle { color: Theme.window }

    function showForm(index) {
        mode = "form"
        formView.load(index)
    }
    function addRow() { showForm(-1) }
    function deleteSelected() {
        const id = page.mode === "form" ? formView.rowId : Bridge.rows.rowId(page.selectedRow)
        if (id > 0) confirmDelete.ask(id)
    }

    FieldsDialog { id: fieldsDialog }
    FormDesignDialog { id: formDesignDialog }
    MatchingRows { id: matchingRows }
    AddFieldDialog { id: addFieldDialog }
    NewTableDialog { id: newTableDialog }
    MakeLookupDialog { id: makeLookupDialog }
    RenameFieldDialog { id: renameFieldDialog }

    Dialog {
        id: deleteFieldConfirm
        property string fieldName: ""
        property string fieldLabel: ""
        function ask(field) { fieldName = field.name; fieldLabel = field.label; open() }
        title: "Delete the field \u201c" + fieldLabel + "\u201d?"
        modal: true
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: 460
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label {
            text: "Everything in that column, in every row, will be gone. This cannot be undone."
            wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            ActionButton { text: "Keep it"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete it"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.deleteField(fieldName); if (!r.ok) toast.show(r.error); fieldsDialog.openFor() }
        onRejected: fieldsDialog.openFor()
    }

    Dialog {
        id: confirmDeleteTable
        property string table: ""
        property int rows: 0
        function ask() {
            table = Bridge.currentTable
            for (const t of Bridge.tables) if (t.name === table) rows = t.rows
            open()
        }
        title: "Delete the table \u201c" + table + "\u201d?"
        modal: true
        anchors.centerIn: parent
        width: 460
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label {
            text: "Its " + rows + (rows === 1 ? " row" : " rows") + ", its form and its reports will be gone. This cannot be undone."
            wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            ActionButton { text: "Keep it"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete the table"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.deleteTable(table); if (!r.ok) toast.show(r.error) }
    }

    Dialog {
        id: confirmDeleteDatabase
        title: "Delete this whole database?"
        modal: true
        anchors.centerIn: parent
        width: 520
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            Label { Layout.fillWidth: true; text: "The file will be removed from your computer:"; wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; text: Bridge.location; font.family: Theme.monoFont; wrapMode: Text.WrapAnywhere }
            Label { Layout.fillWidth: true; text: "Every table and every row in it will be gone. This cannot be undone."; wrapMode: Text.WordWrap; color: Theme.red }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Keep it"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete the database"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.deleteDatabase(); if (!r.ok) toast.show(r.error) }
    }

    FileDialog {
        id: copyDialog
        title: "Save a copy of this database"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "jubadb"
        nameFilters: ["Databases (*.jubadb)"]
        onAccepted: { const r = Bridge.saveCopy(selectedFile); if (!r.ok) toast.show(r.error) }
    }

    Dialog {
        id: renameDatabaseDialog
        objectName: "renameDatabaseDialog"
        property string renameError: ""
        function openFor() { titleBox.text = Bridge.title; renameError = ""; open(); titleBox.forceActiveFocus(); titleBox.selectAll() }
        function go() { const r = Bridge.renameDatabase(titleBox.text.trim()); if (r.ok) close(); else renameError = r.error }
        title: "Rename this database"
        modal: true
        anchors.centerIn: parent
        width: 460
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: ColumnLayout {
            spacing: 8
            TextField { id: titleBox; Layout.fillWidth: true; onAccepted: renameDatabaseDialog.go() }
            Label {
                Layout.fillWidth: true
                text: "The name on Home and at the top of the window." + (Bridge.isLocalFile ? " The file keeps its name." : "")
                color: Theme.lightForeground
                font.pointSize: 10
                wrapMode: Text.WordWrap
            }
            Label { Layout.fillWidth: true; visible: renameDatabaseDialog.renameError !== ""; text: renameDatabaseDialog.renameError; color: Theme.red; wrapMode: Text.WordWrap }
        }
        footer: DialogButtonBox {
            ActionButton { text: "Cancel"; onClicked: renameDatabaseDialog.reject() }
            ActionButton { text: "Rename"; primary: true; enabled: titleBox.text.trim() !== ""; onClicked: renameDatabaseDialog.go() }
        }
    }

    Dialog {
        id: confirmRowNumber
        title: "Add a row number to \u201c" + Bridge.currentTable + "\u201d?"
        modal: true
        anchors.centerIn: parent
        width: 480
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label {
            text: "Jubako adds a numbered id column, so each row can be changed and deleted. Every row and value stays."
                + (Bridge.isLocalFile ? " The table is rebuilt to do it, so a program that made it with special column rules may want to know." : "")
            wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            ActionButton { text: "Not now"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Add the row number"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: { const r = Bridge.addRowNumber(); if (!r.ok) toast.show(r.error) }
    }

    Dialog {
        id: confirmDelete
        property int rowId: 0
        function ask(id) { rowId = id; open() }
        title: "Delete this row?"
        modal: true
        anchors.centerIn: parent
        width: 420
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label { text: "It will be gone for good."; wrapMode: Text.WordWrap }
        footer: DialogButtonBox {
            ActionButton { text: "Keep it"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            ActionButton { text: "Delete it"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
        }
        onAccepted: {
            const r = Bridge.deleteRow(rowId)
            if (!r.ok) toast.show(r.error)
            else if (page.mode === "form") formView.load(Math.min(formView.rowIndex, Bridge.rows.rowCount() - 1))
        }
    }

    header: ToolBar {
        height: 64
        background: Rectangle {
            color: Theme.isDark ? Theme.darkBackground : Theme.darkerBackground
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.muted; opacity: 0.5 }
        }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 12

            ToolButton {
                text: "‹  Home"
                font.pointSize: 12
                onClicked: win.goHome()
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    Layout.fillWidth: true
                    text: Bridge.title
                    font.pointSize: 14
                    font.bold: true
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: Bridge.backendWord + "  ·  " + Bridge.location
                    color: Theme.lightForeground
                    font.pointSize: 9
                    elide: Text.ElideMiddle
                }
            }
            // The File menu, Access's "Backstage": everything about the database as a whole.
            ActionButton {
                text: "Database\u2026"
                objectName: "databaseMenuButton"
                onClicked: { databaseMenu.recentList = Bridge.recent(); databaseMenu.open() }
                Menu {
                    id: databaseMenu
                    objectName: "databaseMenu"
                    property var recentList: []
                    y: parent.height
                    width: 280
                    MenuItem { text: "New database\u2026"; onTriggered: win.startNew() }
                    MenuItem { text: "New from a template\u2026"; onTriggered: win.startTemplate() }
                    MenuItem { text: "Open another\u2026"; onTriggered: win.startOpen() }
                    Menu {
                        title: "Open a recent one"
                        enabled: databaseMenu.recentList.length > 1
                        Repeater {
                            model: databaseMenu.recentList
                            MenuItem {
                                required property int index
                                required property var modelData
                                text: modelData.title + "  \u00b7  " + modelData.backendWord
                                // The open one is first in the list.
                                visible: index > 0
                                height: visible ? implicitHeight : 0
                                onTriggered: win.openRecent(index)
                            }
                        }
                    }
                    MenuSeparator {}
                    MenuItem {
                        text: "Save a copy\u2026"
                        objectName: "menuSaveCopy"
                        enabled: Bridge.isLocalFile
                        onTriggered: { copyDialog.selectedFile = Bridge.copyName(); copyDialog.open() }
                    }
                    MenuItem { text: "Rename\u2026"; objectName: "menuRenameDatabase"; onTriggered: renameDatabaseDialog.openFor() }
                    MenuItem { text: "Close"; onTriggered: win.goHome() }
                    MenuSeparator {}
                    MenuItem {
                        text: "Delete this whole database\u2026"
                        enabled: Bridge.isLocalFile
                        onTriggered: confirmDeleteDatabase.open()
                    }
                    MenuSeparator {}
                    MenuItem { text: "About Jubako"; objectName: "menuAbout"; onTriggered: win.showAbout() }
                }
            }
            ActionButton {
                text: "Export…"
                enabled: Bridge.currentTable !== ""
                onClicked: exportMenu.open()
                Menu {
                    id: exportMenu
                    y: parent.height
                    MenuItem { text: "CSV file"; onTriggered: win.startExport("csv") }
                    MenuItem { text: "Excel file (.xlsx)"; onTriggered: win.startExport("xlsx") }
                    MenuItem { text: "PDF (print report)…"; onTriggered: win.startReport() }
                }
            }
            ActionButton {
                text: "Print report"
                enabled: Bridge.currentTable !== ""
                onClicked: win.startReport()
            }
            ActionButton {
                text: "Import spreadsheet"
                primary: true
                onClicked: win.startImport()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ---- tables --------------------------------------------------------
        Rectangle {
            Layout.preferredWidth: Math.max(160, Math.min(260, page.width * 0.28))
            Layout.fillHeight: true
            color: Theme.darkBackground
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.muted; opacity: 0.5 }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                Label {
                    text: "Tables"
                    font.pointSize: 12
                    font.bold: true
                    color: Theme.lightForeground
                    Layout.leftMargin: 8
                }
                ListView {
                    id: tableList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: Bridge.tables
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        id: item
                        required property var modelData
                        width: tableList.width
                        height: 48
                        hoverEnabled: true
                        property bool current: modelData.name === Bridge.currentTable
                        onClicked: {
                            const r = Bridge.selectTable(modelData.name)
                            if (!r.ok) toast.show(r.error)
                        }
                        background: Rectangle {
                            radius: 8
                            color: item.current ? Theme.selection
                                 : item.hovered ? Theme.lighterBackground : "transparent"
                        }
                        contentItem: ColumnLayout {
                            spacing: 1
                            Label {
                                Layout.fillWidth: true
                                text: item.modelData.name
                                font.pointSize: 12
                                font.bold: item.current
                                elide: Text.ElideRight
                            }
                            Label {
                                text: item.modelData.rows === 1 ? "1 row" : item.modelData.rows + " rows"
                                color: Theme.lightForeground
                                font.pointSize: 9
                            }
                        }
                    }
                }
                Label {
                    visible: Bridge.tables.length === 0
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    text: "No tables yet."
                    color: Theme.lightForeground
                    wrapMode: Text.WordWrap
                }
                ActionButton {
                    text: "New table…"
                    objectName: "newTableButton"
                    Layout.fillWidth: true
                    onClicked: newTableDialog.openFor()
                }
            }
        }

        // ---- rows ------------------------------------------------------------
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            EmptyState {
                anchors.fill: parent
                visible: Bridge.tables.length === 0
                title: "No tables yet"
                text: "Make a table and list its fields, or bring in a spreadsheet: drop it on this window and it becomes a table."
                buttonText: "New table…"
                onClicked: newTableDialog.openFor()
                secondButtonText: "Import spreadsheet"
                onSecondClicked: win.startImport()
            }
            ActionButton {
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                visible: Bridge.tables.length === 0 && Bridge.isLocalFile
                text: "Delete this whole database\u2026"
                onClicked: confirmDeleteDatabase.open()
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 0
                visible: Bridge.tables.length > 0

                RowLayout {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 10
                    spacing: 8
                    ActionButton {
                        text: "Grid"
                        primary: page.mode === "grid"
                        onClicked: page.mode = "grid"
                    }
                    ActionButton {
                        text: "Form"
                        primary: page.mode === "form"
                        onClicked: page.showForm(page.selectedRow >= 0 ? page.selectedRow : 0)
                    }
                    Item { Layout.fillWidth: true }
                    ActionButton { text: "Add row"; onClicked: page.addRow() }
                    ActionButton {
                        text: "Delete row"
                        enabled: Bridge.canEdit && (page.mode === "form" ? formView.rowId > 0 : page.selectedRow >= 0)
                        onClicked: page.deleteSelected()
                    }
                    ActionButton {
                        text: "More\u2026"
                        objectName: "moreButton"
                        onClicked: moreMenu.open()
                        Menu {
                            id: moreMenu
                            x: parent.width - width     // at the right edge: open leftwards
                            y: parent.height
                            width: 340
                            MenuItem { text: "Add field\u2026"; objectName: "menuAddField"; onTriggered: addFieldDialog.openFor(false) }
                            MenuItem { text: "Fields: add, rename or delete\u2026"; onTriggered: fieldsDialog.openFor() }
                            MenuItem { text: "Arrange the form\u2026"; objectName: "menuArrangeForm"; onTriggered: formDesignDialog.openFor() }
                            MenuSeparator {}
                            // The rows on screen, all at once.
                            MenuItem {
                                text: (Bridge.filterWords !== "" ? "These " + Bridge.totalRows + " rows" : "All " + Bridge.totalRows + " rows") + ": what they add up to\u2026"
                                objectName: "menuSummary"
                                enabled: Bridge.totalRows > 0
                                onTriggered: matchingRows.openSummary()
                            }
                            MenuItem {
                                text: (Bridge.filterWords !== "" ? "These " + Bridge.totalRows + " rows" : "All " + Bridge.totalRows + " rows") + ": change a field\u2026"
                                objectName: "menuChangeRows"
                                enabled: Bridge.totalRows > 0
                                onTriggered: matchingRows.openChange()
                            }
                            MenuItem {
                                text: (Bridge.filterWords !== "" ? "These " + Bridge.totalRows + " rows" : "All " + Bridge.totalRows + " rows") + ": delete them\u2026"
                                objectName: "menuDeleteRows"
                                enabled: Bridge.totalRows > 0
                                onTriggered: matchingRows.openDelete()
                            }
                            MenuSeparator {}
                            MenuItem { text: "Delete this table\u2026"; onTriggered: confirmDeleteTable.ask() }
                        }
                    }
                }

                FilterBar {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 10
                    visible: Bridge.fields.length > 0
                }

                // A table made outside Jubako without a row number: readable, not editable, until it has one.
                Rectangle {
                    objectName: "noRowNumberBanner"
                    Layout.fillWidth: true
                    Layout.bottomMargin: 10
                    visible: !Bridge.canEdit && Bridge.currentTable !== ""
                    implicitHeight: bannerRow.implicitHeight + 20
                    radius: 8
                    color: Theme.lighterBackground
                    border.color: Theme.yellow
                    RowLayout {
                        id: bannerRow
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 12
                        Label {
                            Layout.fillWidth: true
                            text: "This table came from outside Jubako and has no row number, so its rows cannot be changed here."
                            wrapMode: Text.WordWrap
                        }
                        ActionButton { text: "Add a row number\u2026"; primary: true; onClicked: confirmRowNumber.open() }
                    }
                }

                FormView {
                    id: formView
                    objectName: "formView"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: page.mode === "form"
                    onDeleteRequested: function(id) { confirmDelete.ask(id) }
                }

                HorizontalHeaderView {
                    id: headerView
                    Layout.fillWidth: true
                    visible: page.mode === "grid"
                    syncView: grid
                    clip: true
                    // Tap a heading to sort by it: up, then down, then back to the order rows were added.
                    delegate: Rectangle {
                        id: headingCell
                        required property string display
                        required property int column
                        property string fieldName: Bridge.rows.nameAt(column)
                        property var sortItem: {
                            const order = Bridge.sort
                            for (let i = 0; i < order.length; i++) if (order[i].field === fieldName) return order[i]
                            return null
                        }
                        implicitWidth: 100
                        implicitHeight: 36
                        color: headingTap.containsMouse ? Qt.lighter(Theme.lighterBackground, 1.12) : Theme.lighterBackground
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.muted }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 8
                            spacing: 4
                            Label {
                                Layout.fillWidth: true
                                verticalAlignment: Text.AlignVCenter
                                text: headingCell.display
                                font.bold: true
                                elide: Text.ElideRight
                            }
                            Label {
                                visible: headingCell.sortItem !== null
                                text: headingCell.sortItem && headingCell.sortItem.descending ? "\u25bc" : "\u25b2"
                                color: Theme.accent
                                font.pointSize: 8
                            }
                        }
                        MouseArea {
                            id: headingTap
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                const r = Bridge.sortBy(headingCell.fieldName)
                                if (!r.ok) toast.show(r.error)
                            }
                        }
                    }
                }

                TableView {
                    id: grid
                    objectName: "rowsGrid"
                    Layout.fillWidth: true
                    // No rows: the headings stay, and the message below takes the space.
                    Layout.fillHeight: !page.noRows
                    Layout.preferredHeight: page.noRows ? 0 : -1
                    visible: page.mode === "grid"
                    clip: true
                    model: Bridge.rows
                    columnSpacing: 0
                    rowSpacing: 0
                    boundsBehavior: Flickable.StopAtBounds
                    columnWidthProvider: function(column) { return Bridge.rows.columnWidth(column) }
                    ScrollBar.vertical: ScrollBar {}
                    ScrollBar.horizontal: ScrollBar {}

                    // Tap a row to pick it; double-tap (or Enter / F2) a cell to type in it.
                    selectionModel: ItemSelectionModel {}
                    selectionBehavior: TableView.SelectRows
                    editTriggers: TableView.DoubleTapped | TableView.EditKeyPressed

                    delegate: Rectangle {
                        id: cellItem
                        required property string display
                        required property int row
                        required property int column
                        required property bool current
                        implicitWidth: 100
                        implicitHeight: 34
                        color: row === grid.currentRow ? Theme.selection
                             : row % 2 === 0 ? Theme.base : Theme.alternateBase
                        Label {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            verticalAlignment: Text.AlignVCenter
                            text: cellItem.display
                            elide: Text.ElideRight
                            color: cellItem.column === 0 ? Theme.lightForeground : Theme.foreground
                            font.family: cellItem.column === 0 ? Theme.monoFont : win.font.family
                        }
                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            border.width: cellItem.current && cellItem.column > 0 ? 2 : 0
                            border.color: Theme.accent
                        }

                        TableView.editDelegate: TextField {
                            anchors.fill: parent
                            text: display
                            font.pointSize: 11
                            selectByMouse: true
                            Component.onCompleted: { selectAll(); forceActiveFocus() }
                            TableView.onCommit: display = text
                        }
                    }

                    Connections {
                        target: Bridge
                        function onTableChanged() {
                            grid.contentX = 0
                            grid.contentY = 0
                            grid.forceLayout()
                        }
                    }
                }

                EmptyState {
                    objectName: "noRowsState"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: page.noRows
                    title: "No rows yet"
                    text: "This table is empty. Press Add row, or import a spreadsheet."
                    buttonText: "Add row"
                    onClicked: page.addRow()
                }

                Label {
                    objectName: "rowsStatus"
                    Layout.topMargin: 8
                    text: (Bridge.filterWords !== ""
                        ? (Bridge.totalRows === 0
                            ? "No rows where " + Bridge.filterWords + ". Press Clear to see all " + Bridge.allRows + "."
                            : "Showing " + Bridge.totalRows + " of " + Bridge.allRows + " rows where " + Bridge.filterWords
                              + (Bridge.shownRows < Bridge.totalRows ? " (first " + Bridge.shownRows + ")" : ""))
                        : Bridge.shownRows === Bridge.totalRows
                        ? (Bridge.totalRows === 1 ? "1 row" : Bridge.totalRows + " rows")
                        : "Showing the first " + Bridge.shownRows + " of " + Bridge.totalRows + " rows")
                        + (Bridge.sortWords !== "" ? "  \u00b7  sorted by " + Bridge.sortWords : "")
                    color: Bridge.filterWords !== "" ? Theme.yellow : Theme.lightForeground
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                    font.pointSize: 10
                }
            }
        }
    }
}
