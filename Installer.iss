; Instalador parametrizado por produto (veja product.py). Compilar com:
;   ISCC.exe /DProduct=giro360    Installer.iss   -> Output\Giro360-Setup.exe
;   ISCC.exe /DProduct=fotocabine Installer.iss   -> Output\FotoCabine-Setup.exe
; (build_scripts\build_products.ps1 faz o PyInstaller + este passo pros dois.)

#ifndef Product
  #error Informe o produto: ISCC /DProduct=giro360 (ou fotocabine) Installer.iss
#endif

#define MyAppVersion "1.0.0"

#if Product == "giro360"
  #define MyAppName "Giro360"
  #define MyAppId "{{B3B6E9B0-6C5C-4E58-8F7B-9B7C7A2E3B10}"
  #define MyAppDescription "Cabine giratória 360°"
#elif Product == "fotocabine"
  #define MyAppName "FotoCabine"
  #define MyAppId "{{5E0C7D52-3A41-4D0E-9B6F-1C2A8E4F7A91}"
  #define MyAppDescription "Cabine de fotos e tirinhas"
#else
  #error Produto desconhecido
#endif

#define MyAppPublisher MyAppName
#define MyAppExeName MyAppName + ".exe"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename={#MyAppName}-Setup
SetupIconFile=assets\{#Product}.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardImageFile=assets\{#Product}_wizard.bmp
WizardSmallImageFile=assets\{#Product}_small.bmp
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
Source: "dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "%SystemDrive%\*"
Source: "README_INSTALACAO.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Leia-me (driver da camera)"; Filename: "{app}\README_INSTALACAO.txt"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\README_INSTALACAO.txt"; Description: "Ver instrucoes sobre o driver USB da camera"; Flags: postinstall shellexec skipifsilent unchecked
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked
