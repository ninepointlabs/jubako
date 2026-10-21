import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// What an empty screen says. It teaches by pointing at the one thing to do.
Item {
    id: root
    property string title: ""
    property string text: ""
    property string buttonText: ""
    property string secondButtonText: ""   // a second way, beside the first
    signal clicked()
    signal secondClicked()

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 520)
        spacing: 12

        Label {
            Layout.fillWidth: true
            text: root.title
            font.pointSize: 20
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }
        Label {
            Layout.fillWidth: true
            text: root.text
            color: Theme.lightForeground
            font.pointSize: 12
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
        }
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 12
            spacing: 12
            BigButton {
                visible: root.buttonText !== ""
                text: root.buttonText
                primary: true
                implicitHeight: 64
                onClicked: root.clicked()
            }
            BigButton {
                visible: root.secondButtonText !== ""
                text: root.secondButtonText
                implicitHeight: 64
                onClicked: root.secondClicked()
            }
        }
    }
}
