; Instalador de Victoria II Mod Studio para Windows (Inno Setup 6).
;
; Empaqueta la carpeta que deja PyInstaller (dist\Victoria II Mod Studio\). Uso, desde la raiz del proyecto:
;   iscc /DAppVersion=0.1.0 packaging\windows\vic2studio.iss
; Resultado: dist\VictoriaIIModStudio-<version>-setup.exe
;
; Se instala para el usuario actual (sin permisos de administrador) en
; %LOCALAPPDATA%\Programs\Victoria II Mod Studio, con acceso en el menu Inicio y, si se elige, en el escritorio.
; Las preferencias (%APPDATA%\VIIMOD) y los mods no se tocan al desinstalar.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Victoria II Mod Studio"
#define AppExe "Victoria II Mod Studio.exe"
#define Root SourcePath + "..\.."

[Setup]
AppId={{6E0B7C1A-3F52-4C8E-9A51-2D7A3B9C4F10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=VIIMOD
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Root}\dist
OutputBaseFilename=VictoriaIIModStudio-{#AppVersion}-setup
SetupIconFile={#Root}\packaging\icons\vic2studio.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#Root}\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Una version nueva sustituye a la anterior entera: sin restos de bibliotecas que ya no se usan.
Type: filesandordirs; Name: "{app}\_internal"
