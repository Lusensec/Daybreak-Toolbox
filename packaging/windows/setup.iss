; 破晓·工具箱 —— Windows 安装程序（Inno Setup 6.3+ / 7）
; 由 CI 构建：iscc /D:AppVersion=v2.0.9 /D:AppVerNum=2.0.9 /D:ExePath=dist\DaybreakToolbox.exe packaging\windows\setup.iss
; 本地构建（可选）：先 pnpm build + PyInstaller 出 dist\DaybreakToolbox.exe，再 ISCC 本文件。
;
; 设计要点：
;  - 默认安装到 %LOCALAPPDATA%\DaybreakToolbox（免管理员/UAC；程序会在 exe 旁写 config/ 与 daybreak.log，
;    默认目录可写；用户改到 Program Files 等只读目录时 config 写入会受限——README 已注明）
;  - 产物：Daybreak-Toolbox-<AppVersion>-win-setup.exe（per-user 安装，卸载项在 HKCU）

#define AppVersion "v2.0.9"   ; 资产文件名用（/D:AppVersion= 覆盖）
#define AppVerNum  "2.0.9"   ; Setup 版本号（无 v 前缀，/D:AppVerNum= 覆盖）
; 相对路径基于脚本目录（packaging/windows/）解析
#define ExePath    "..\..\dist\DaybreakToolbox.exe"  ; onefile 产物

[Setup]
AppId={{9C7D5E2A-4B1F-4C6E-8A3D-B2E7F05A1C48}}
AppName=Daybreak Toolbox
AppVersion={#AppVerNum}
AppVerName=Daybreak Toolbox {#AppVersion}
AppPublisher=Lusensec
DefaultDirName={localappdata}\DaybreakToolbox
DefaultGroupName=Daybreak Toolbox
OutputDir=out
OutputBaseFilename=Daybreak-Toolbox-{#AppVersion}-win-setup
SetupIconFile=..\daybreak_logo.ico
UninstallDisplayIcon={app}\DaybreakToolbox.exe
UninstallDisplayName=Daybreak Toolbox
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#AppVerNum}
VersionInfoProductName=Daybreak Toolbox

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#ExePath}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Daybreak Toolbox"; Filename: "{app}\DaybreakToolbox.exe"
; 开始菜单卸载项由 Inno 自动生成（[Setup] UninstallDisplayName/UninstallDisplayIcon）
Name: "{autodesktop}\Daybreak Toolbox"; Filename: "{app}\DaybreakToolbox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DaybreakToolbox.exe"; Description: "Run Daybreak Toolbox now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 有意不自动清理 config/ 与 daybreak.log（用户数据：菜单/工具配置）——卸载后保留在安装目录，可手动删除

[Messages]
SetupAppTitle=Daybreak Toolbox {#AppVersion} Setup
ReadyDeleteText=
