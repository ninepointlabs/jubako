Name:           jubako
Version:        0.4.7
Release:        1%{?dist}
Summary:        A simple desktop database, in the spirit of Microsoft Access
License:        MIT
URL:            https://github.com/ninepointlabs/jubako
Source0:        %{url}/archive/refs/tags/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3 >= 3.11
Requires:       python3-pyside6 >= 6.6
Requires:       qt6-qtdeclarative
Recommends:     python3-openpyxl
Suggests:       python3-psycopg3
Suggests:       python3-PyMySQL

%description
Make a database, put a spreadsheet in it, look at your rows, print a tidy
list. No SQL to learn, no server to set up. A Qt Quick window, a command
line and an MCP server for agents, over one SQLite file per database.

%prep
%autosetup -n %{name}-%{version}

%build

%install
packaging/stage.sh %{buildroot}
# rpm keeps docs and licences through %%doc and %%license below.
rm -rf %{buildroot}%{_docdir}/%{name} %{buildroot}%{_datadir}/licenses/%{name}

%files
%license LICENSE
%doc README.md
%{_bindir}/jubako
%{_bindir}/jubako-app
%{_bindir}/jubako-mcp
%{_prefix}/lib/jubako/
%{_datadir}/applications/jubako.desktop
%{_datadir}/icons/hicolor/scalable/apps/jubako.svg

%changelog
* Mon Oct 19 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.7-1
- An AppImage for other Linux distributions, attached to each release.
* Sat Oct 17 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.6-1
- An About screen, from the home screen and the Database... menu.
* Sun Oct 11 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.5-1
- The Contacts template puts each contact in a group.
* Sun Oct 11 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.4-1
- The Home collection template ties each loan to the person who has it.
* Sun Oct 11 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.3-1
- The Inventory template ties each item to its supplier; a new Customer
  service database opens on its tickets again.
* Sun Oct 11 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.2-1
- The Customer service template ties each ticket to its customer; the MCP
  server refuses arguments a tool does not take.
* Sun Oct 11 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.1-1
- The Projects and tasks template ties each task to its project.
* Sat Oct 10 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.4.0-1
- Lookup fields: a row of one table points at a row of another.
* Sat Oct 10 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.3.0-1
- Templates, rules and sorting, rows in bulk, grouped reports with totals,
  no-repeats fields, the form arranger and the Database menu.
* Sat Oct 10 2026 Nine Point Labs <179739321+ninepointlabs@users.noreply.github.com> - 0.2.0-1
- Renamed from Omarchy-DB; first packaged release.
