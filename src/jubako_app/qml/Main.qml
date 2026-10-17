import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

// The one window. Two screens live in the stack: Home, and the open database.
// Every flow (new / open / import) starts here so the pages stay simple.
ApplicationWindow {
    id: win
    visible: true
    width: 1080
    height: 720
    minimumWidth: 720
    minimumHeight: 480
    title: Bridge.isOpen ? Bridge.title + " — Jubako" : "Jubako"
    color: Theme.window
    font.pointSize: 11

    // The Omarchy theme, as the palette every control (and every dialog) paints with.
    // Fusion would otherwise use its own stock palette for the system colour scheme.
    palette.window: Theme.window
    palette.windowText: Theme.foreground
    palette.base: Theme.base
    palette.alternateBase: Theme.alternateBase
    palette.text: Theme.foreground
    palette.placeholderText: Theme.darkForeground
    palette.button: Theme.lighterBackground
    palette.buttonText: Theme.foreground
    palette.brightText: Theme.brightForeground
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.highlightedText
    palette.link: Theme.blue
    palette.toolTipBase: Theme.lighterBackground
    palette.toolTipText: Theme.foreground
    palette.light: Theme.lighterBackground
    palette.midlight: Theme.lighterBackground
    palette.mid: Theme.muted
    palette.dark: Theme.darkerBackground
    palette.shadow: Theme.darkerBackground
    palette.disabled.windowText: Theme.darkForeground
    palette.disabled.text: Theme.darkForeground
    palette.disabled.buttonText: Theme.darkForeground
    palette.disabled.button: Theme.window

    // A spreadsheet picked before any database exists: it becomes a new one.
    property string pendingSpreadsheet: ""

    StackView {
        id: stack
        anchors.fill: parent
        initialItem: homeComponent
        // Keep it calm: no sliding pages.
        pushEnter: Transition {}
        pushExit: Transition {}
        popEnter: Transition {}
        popExit: Transition {}
    }

    Component { id: homeComponent; HomePage {} }
    Component { id: databaseComponent; DatabasePage {} }

    Connections {
        target: Bridge
        function onDatabaseChanged() {
            if (Bridge.isOpen && stack.depth === 1)
                stack.push(databaseComponent)
            else if (!Bridge.isOpen && stack.depth > 1)
                stack.pop(null)
        }
        function onMessage(text) { toast.show(text) }
    }

    // ---- flows -----------------------------------------------------------
    function startNew() { newDialog.openFor("new", "sqlite", "", {}, "") }
    function startTemplate() {
        const list = Bridge.templates()
        newDialog.openFor("new", "sqlite", "", {}, list.length > 0 ? list[0].key : "")
    }
    function startOpen() { openDbDialog.open() }
    function startImport() { importDialog.open() }
    function goHome() { Bridge.closeDatabase() }
    function showAbout() { aboutDialog.open() }

    function openRecent(index) {
        const r = Bridge.openRecent(index)
        if (r.ok)
            return
        if (r.needsConnection)
            newDialog.openFor("open", r.backend, r.title, r.connection)
        else
            toast.show(r.error)
    }

    function openFile(url) {
        const r = Bridge.openDatabase("sqlite", url, {})
        if (!r.ok)
            toast.show(r.error)
    }

    function importFile(url) {
        if (!Bridge.isOpen) {
            // First run: the spreadsheet becomes a brand new database, then the wizard opens.
            win.pendingSpreadsheet = url
            saveDbDialog.selectedFile = Bridge.documentsFolder() + "/" + Bridge.suggestedDatabaseName(url)
            saveDbDialog.open()
            return
        }
        importWizard.openFor(url)
    }

    function startReport() {
        if (Bridge.isOpen && Bridge.currentTable !== "")
            reportDialog.openFor(Bridge.currentTable, Bridge.fields)
    }

    function startExport(format) {
        if (!Bridge.isOpen || Bridge.currentTable === "")
            return
        exportDialog.format = format
        exportDialog.nameFilters = format === "xlsx" ? ["Excel files (*.xlsx)"] : ["CSV files (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = Bridge.documentsFolder() + "/" + Bridge.currentTable + "." + format
        exportDialog.open()
    }

    function dropped(urls) {
        if (!urls || urls.length === 0)
            return
        const url = String(urls[0])
        const lower = url.toLowerCase()
        if (lower.endsWith(".jubadb") || lower.endsWith(".omadb") || lower.endsWith(".sqlite") || lower.endsWith(".sqlite3") || lower.endsWith(".db"))
            openFile(url)
        else
            importFile(url)
    }

    // ---- dialogs ---------------------------------------------------------
    NewDatabaseDialog {
        id: newDialog
        onSqliteChosen: function(chosenTitle) {
            const stem = newDialog.templateKey !== "" ? newDialog.templateKey.replace(/_/g, "-") : "my-database"
            saveDbDialog.selectedFile = Bridge.documentsFolder() + "/" + stem + ".jubadb"
            saveDbDialog.open()
        }
    }

    FileDialog {
        id: saveDbDialog
        title: "Save the new database"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "jubadb"
        nameFilters: ["Databases (*.jubadb)"]
        currentFolder: Bridge.documentsFolder()
        onAccepted: {
            let r
            if (win.pendingSpreadsheet !== "") {
                const sheet = win.pendingSpreadsheet
                win.pendingSpreadsheet = ""
                r = Bridge.newDatabase("sqlite", selectedFile, Bridge.suggestedDatabaseName(sheet).replace(/\.jubadb$/, "").replace(/[-_]/g, " "), {})
                if (r.ok)
                    importWizard.openFor(sheet)
            } else if (newDialog.templateKey !== "") {
                r = Bridge.newFromTemplate("sqlite", selectedFile, newDialog.chosenTitle, {},
                                           newDialog.templateKey, newDialog.sampleRows)
            } else {
                r = Bridge.newDatabase("sqlite", selectedFile, newDialog.chosenTitle, {})
            }
            if (!r.ok)
                toast.show(r.error)
        }
        onRejected: win.pendingSpreadsheet = ""
    }

    FileDialog {
        id: openDbDialog
        title: "Open a database"
        nameFilters: ["Databases (*.jubadb *.omadb *.sqlite *.sqlite3 *.db)", "All files (*)"]
        currentFolder: Bridge.documentsFolder()
        onAccepted: win.openFile(selectedFile)
    }

    FileDialog {
        id: importDialog
        title: "Pick a spreadsheet"
        nameFilters: ["Spreadsheets (*.csv *.tsv *.txt *.xlsx *.xlsm)", "All files (*)"]
        currentFolder: Bridge.homeFolder()
        onAccepted: win.importFile(selectedFile)
    }

    ImportDialog { id: importWizard }
    AboutDialog { id: aboutDialog }
    ReportDialog { id: reportDialog }

    FileDialog {
        id: exportDialog
        property string format: "csv"
        title: "Save the table as a file"
        fileMode: FileDialog.SaveFile
        currentFolder: Bridge.documentsFolder()
        onAccepted: {
            const r = Bridge.exportTable(selectedFile, format)
            if (!r.ok) toast.show(r.error)
        }
    }

    FileDialog {
        id: pdfDialog
        title: "Save the report as a PDF"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "pdf"
        nameFilters: ["PDF files (*.pdf)"]
        currentFolder: Bridge.documentsFolder()
        onAccepted: {
            const r = Report.savePdf(selectedFile)
            if (!r.ok) toast.show(r.error)
        }
    }

    Dialog {
        id: replaceDialog
        property string table: ""
        property string spreadsheet: ""
        property bool fromWizard: false
        title: "Replace the table “" + table + "”?"
        modal: true
        anchors.centerIn: parent
        width: 480
        padding: 20
        Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }
        contentItem: Label {
            text: "It is already in this database. Its rows will be thrown away."
            wrapMode: Text.WordWrap
        }
        footer: DialogButtonBox {
            ActionButton {
                text: "Keep what I have"
                DialogButtonBox.buttonRole: DialogButtonBox.RejectRole
            }
            ActionButton {
                text: "Replace it"
                primary: true
                DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole
            }
        }
        onAccepted: {
            if (fromWizard) {
                fromWizard = false
                tables = []
                importWizard.go(true)
                return
            }
            const r = Bridge.importSpreadsheet(spreadsheet, true)
            if (!r.ok)
                toast.show(r.error)
        }
    }

    // Drop a spreadsheet (or a database file) anywhere on the window.
    DropArea {
        anchors.fill: parent
        onDropped: function(drop) {
            if (drop.hasUrls) {
                win.dropped(drop.urls)
                drop.accept()
            }
        }
    }

    Toast { id: toast }
}
