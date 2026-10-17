import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// About Jubako: version, who made it, licence, support, privacy, toolkit versions.
Dialog {
    id: dialog
    objectName: "aboutDialog"
    property bool showLicense: false
    onAboutToShow: showLicense = false

    modal: true
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(560, parent ? parent.width - 40 : 560)
    padding: 20
    closePolicy: Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Theme.isDark ? "#99000000" : "#55000000" }

    contentItem: ColumnLayout {
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Image {
                source: AppInfo.icon
                visible: String(AppInfo.icon) !== ""
                sourceSize: Qt.size(72, 72)
                Layout.preferredWidth: 72
                Layout.preferredHeight: 72
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label { text: AppInfo.name; font.pointSize: 22; font.bold: true }
                Label {
                    Layout.fillWidth: true
                    text: AppInfo.tagline
                    color: Theme.lightForeground
                    wrapMode: Text.WordWrap
                }
                Label { text: "Version " + AppInfo.version; color: Theme.darkForeground; font.pointSize: 10 }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            Layout.topMargin: 4
            columns: 2
            columnSpacing: 16
            rowSpacing: 8

            Label { text: "Made by"; color: Theme.lightForeground; font.pointSize: 10 }
            Label { text: AppInfo.organization }

            Label { text: "Created"; color: Theme.lightForeground; font.pointSize: 10 }
            Label { text: AppInfo.created }

            Label { text: "License"; color: Theme.lightForeground; font.pointSize: 10 }
            RowLayout {
                spacing: 10
                Label { text: AppInfo.license + ", " + AppInfo.copyright }
                ActionButton {
                    objectName: "aboutLicense"
                    text: dialog.showLicense ? "Hide" : "Read it"
                    onClicked: dialog.showLicense = !dialog.showLicense
                }
            }

            Label { text: "Support"; color: Theme.lightForeground; font.pointSize: 10 }
            RowLayout {
                spacing: 10
                Label { text: AppInfo.supportEmail }
                ActionButton {
                    text: "Email"
                    onClicked: Qt.openUrlExternally("mailto:" + AppInfo.supportEmail + "?subject="
                        + encodeURIComponent("Jubako " + AppInfo.version) + "&body="
                        + encodeURIComponent("\n\n--\n" + AppInfo.details))
                }
                ActionButton { text: "Copy"; onClicked: AppInfo.copy(AppInfo.supportEmail) }
            }

            Label { text: "Privacy"; color: Theme.lightForeground; font.pointSize: 10; Layout.alignment: Qt.AlignTop }
            Label {
                objectName: "aboutPrivacy"
                Layout.fillWidth: true
                text: "No accounts, no telemetry. Jubako only goes on the network to reach a PostgreSQL "
                    + "or MySQL/MariaDB server you point it at. A file database stays on this computer, "
                    + "where you saved it. The MCP server talks to your agent over stdin/stdout and opens "
                    + "no network port. The recent list is kept in ~/.local/state/jubako/, and server "
                    + "passwords are never saved."
                wrapMode: Text.WordWrap
            }

            Label { text: "Built with"; color: Theme.lightForeground; font.pointSize: 10 }
            Label {
                Layout.fillWidth: true
                text: "Qt " + AppInfo.qtVersion + " and Qt Quick, PySide6 " + AppInfo.pysideVersion
                    + ", Python " + AppInfo.pythonVersion
                color: Theme.lightForeground
                wrapMode: Text.WordWrap
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            visible: dialog.showLicense
            color: Theme.base
            radius: 8
            border.width: 1
            border.color: Theme.muted
            Flickable {
                id: licenseView
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                contentHeight: licenseText.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                Label {
                    id: licenseText
                    objectName: "aboutLicenseText"
                    width: licenseView.width - 8
                    text: AppInfo.licenseText
                    font.pointSize: 10
                    color: Theme.lightForeground
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    footer: DialogButtonBox {
        ActionButton {
            text: "Copy version details"
            DialogButtonBox.buttonRole: DialogButtonBox.ActionRole
            onClicked: AppInfo.copy(AppInfo.details)
        }
        ActionButton { text: "Close"; primary: true; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
    }
}
