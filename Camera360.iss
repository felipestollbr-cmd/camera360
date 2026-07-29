; Instalador do Camera360 - Controle de Camera
; Compilar com: ISCC.exe Camera360.iss  (gera Output\Camera360-Setup.exe)

#define MyAppName "Camera360"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Camera360"
#define MyAppExeName "Camera360.exe"

[Setup]
AppId={{B3B6E9B0-6C5C-4E58-8F7B-9B7C7A2E3B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Camera360-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Area de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "dist\Camera360\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "%SystemDrive%\*"
Source: "README_INSTALACAO.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Leia-me (driver da camera)"; Filename: "{app}\README_INSTALACAO.txt"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\README_INSTALACAO.txt"; Description: "Ver instrucoes sobre o driver USB da camera"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked
