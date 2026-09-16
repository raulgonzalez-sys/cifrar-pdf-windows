; Instalador de Cifrar PDF (FISAT) para Windows 10/11 x64.
;
; Compilar (tras generar dist\CifrarPDF con PyInstaller):
;     iscc empaquetar\CifrarPDF.iss
;
; Instalación POR EQUIPO (necesita administrador), uso OPT-IN POR PERSONA: el
; programa queda en Program Files, pero no arranca nada por su cuenta — el
; autoarranque del vigilante se escribe en HKCU cuando cada trabajador/a crea su
; primera carpeta. Quien no lo use no tiene nada corriendo.

#define MiApp "Cifrar PDF"
#define MiVersion "1.1.0"
#define MiEditor "Fundación FISAT Salesianos Social"
#define MiExe "CifrarPDF.exe"

[Setup]
AppId={{9F3C6A54-2E71-4A6B-9C0D-1F2A7B5D8E31}
AppName={#MiApp}
AppVersion={#MiVersion}
AppVerName={#MiApp} {#MiVersion}
AppPublisher={#MiEditor}
DefaultDirName={autopf}\FISAT\CifrarPDF
DefaultGroupName=FISAT
DisableProgramGroupPage=yes
PrivilegesRequired=admin
; Solo Windows 10 x64 o superior: PyQt6 no admite menos, y es mejor rechazar
; con un mensaje claro que instalarse y fallar al arrancar.
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\salida
OutputBaseFilename=CifrarPDF-Setup-{#MiVersion}
SetupIconFile=..\recursos\cifrarpdf.ico
UninstallDisplayIcon={app}\{#MiExe}
UninstallDisplayName={#MiApp} (FISAT)
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#MiVersion}
VersionInfoCompany={#MiEditor}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\dist\CifrarPDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MiApp}"; Filename: "{app}\{#MiExe}"; Comment: "Cifra los PDF que sueltas en tus carpetas"
Name: "{autoprograms}\{#MiApp}"; Filename: "{app}\{#MiExe}"

[Run]
Filename: "{app}\{#MiExe}"; Description: "Abrir {#MiApp} ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Detiene el vigilante del usuario que desinstala, para que no queden ficheros
; en uso. Si no hay ninguno en marcha, no hace nada.
Filename: "{app}\{#MiExe}"; Parameters: "--parar"; Flags: runhidden waituntilterminated; RunOnceId: "PararVigilante"

; NOTA: al desinstalar NO se borran ni las carpetas del Escritorio, ni la
; configuración (%APPDATA%\FISAT\CifrarPDF), ni las contraseñas del
; Administrador de credenciales. Es deliberado: son datos de la persona, y
; borrar sus PDF o sus contraseñas al quitar un programa sería inaceptable.
; Para dejarlo todo limpio, en la ventana está «Quitar todas las carpetas».
