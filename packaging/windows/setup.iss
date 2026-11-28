; 破晓·工具箱 —— Windows 安装程序（Inno Setup 6.3+ / 7）
; 由 CI 构建：iscc /D:AppVersion=v2.0.9 /D:AppVerNum=2.0.9 /D:ExePath=dist\DaybreakToolbox.exe packaging\windows\setup.iss
; 本地构建（可选）：先 pnpm build + PyInstaller --onedir 出 dist\DaybreakToolbox\，再 ISCC 本文件。
;
; 设计要点：
;  - 默认安装到 %LOCALAPPDATA%\DaybreakToolbox（免管理员/UAC；程序会在 exe 旁写 config/ 与 daybreak.log，
;    默认目录可写；用户改到 Program Files 等只读目录时 config 写入会受限——README 已注明）
;  - 产物：Daybreak-Toolbox-<AppVersion>-win-setup.exe（per-user 安装，卸载项在 HKCU）

; 版本常量来自 _defines.inc（CI 构建前覆盖写入当前 tag；本地构建直接改该文件）。
; 不用 iscc /D: 传参——实测 runner 上 /D: 参数未生效（脚本 #define 又覆盖命令行的双重怪癖）。
#include "_defines.inc"
; v2.1.1：产物改为 onedir（dist\DaybreakToolbox\ 目录 + _internal\）——去掉每次启动的运行时
; 自解压（onefile 每次双击都要解 394 文件/63MB 到 %TEMP%，实测占启动耗时 3s）
#define DistDir    "..\..\dist\DaybreakToolbox"

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
UninstallDisplayName=破晓·工具箱
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#AppVerNum}
VersionInfoProductName=Daybreak Toolbox

[Languages]
; v2.0.17：简体中文界面（安装向导 + 卸载对话框；官方翻译文件，Inno 6.5+，已入库 languages/）
; 单一语言 → 无语言选择页；卸载器由本 .iss 生成故同步中文化
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
; v2.2.3：排除运行时生成的 WebView2 用户缓存（data\）与日志——本地真机验证后这些目录会
; 长大到数十 MB，打进安装包既增大体积又把验证机的浏览器状态带给所有用户（首次启动自动重建）。
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\*,daybreak.log"

[Icons]
Name: "{group}\Daybreak Toolbox"; Filename: "{app}\DaybreakToolbox.exe"
; 开始菜单卸载项由 Inno 自动生成（[Setup] UninstallDisplayName/UninstallDisplayIcon）
Name: "{autodesktop}\Daybreak Toolbox"; Filename: "{app}\DaybreakToolbox.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DaybreakToolbox.exe"; Description: "现在运行 破晓·工具箱"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 有意不自动清理 config/ 与 daybreak.log（用户数据：菜单/工具配置）——卸载后保留在安装目录，可手动删除

[Messages]
; 中文化覆盖（官方 .isl 已翻译全部标准串；此处仅覆盖应用名相关标题——键必须为 Inno 标准消息 ID）
SetupAppTitle=破晓·工具箱 {#AppVersion} 安装向导
UninstallAppTitle=破晓·工具箱 卸载向导
