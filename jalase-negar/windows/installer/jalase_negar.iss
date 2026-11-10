; Inno Setup script for the Jalase-Negar Windows installer.
; Built by .github/workflows/jalase-negar-windows.yml:  iscc /DAppVersion=1.1.4 windows\installer\jalase_negar.iss
; The input is the Flutter release folder build\windows\x64\runner\Release (run from jalase-negar\).
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6B0F3D52-4E1A-4C7B-9A53-0A1B2C3D4E5F}
AppName=Jalase-Negar
AppVersion={#AppVersion}
AppPublisher=SedaSanj
DefaultDirName={autopf}\Jalase-Negar
DefaultGroupName=Jalase-Negar
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\jalase_negar.exe
SetupIconFile=..\runner\resources\app_icon.ico
OutputDir=..\..\installer-out
OutputBaseFilename=JalaseNegar-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install by default (no admin prompt); the user may choose "for all users".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
WizardImageFile=wizard.bmp,wizard@2x.bmp
WizardSmallImageFile=wizard-small.bmp,wizard-small@2x.bmp
WizardImageAlphaFormat=none

[Messages]
WelcomeLabel1=Welcome to Jalase-Negar
WelcomeLabel2=Jalase-Negar records your meetings and transcribes Persian speech on this computer, then sends the text to SedaSanj.%n%nClick Next to continue.
FinishedHeadingLabel=Jalase-Negar is ready
FinishedLabel=Jalase-Negar has been installed. Grant the microphone permission the first time you record.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\..\build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Jalase-Negar"; Filename: "{app}\jalase_negar.exe"
Name: "{autodesktop}\Jalase-Negar"; Filename: "{app}\jalase_negar.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\jalase_negar.exe"; Description: "Launch Jalase-Negar"; Flags: nowait postinstall skipifsilent
