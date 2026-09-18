; Translation Studio: per-user installation with tracked-file-only removal.
; Compile with Inno Setup 7.1.0. AppSource is a verified, dedicated staging tree.
; Production identities are fixed here. QA identities are compile-time only.
#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.py
#endif
#ifndef BuildId
  #error BuildId must be supplied by build_installer.py
#endif
#ifndef AppSource
  #error AppSource must be supplied by build_installer.py
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_installer.py
#endif
#ifndef QAAppId
  #define InstallerAppId "3A2EF1A7-51E4-4D2F-8121-F1C5EDE795AC"
  #define InstallerMutex "TranslationStudio.App.3A2EF1A7-51E4-4D2F-8121-F1C5EDE795AC"
  #define InstallerGroup "Translation Studio"
  #define InstallerDisplayName "치pdf"
  #define InstallerShortcut "치pdf"
#else
  #ifndef QAMutex
    #error QAAppId requires QAMutex
  #endif
  #ifndef QAGroupName
    #error QAAppId requires QAGroupName
  #endif
  #define InstallerAppId QAAppId
  #define InstallerMutex QAMutex
  #define InstallerGroup QAGroupName
  #define InstallerDisplayName QAGroupName
  #define InstallerShortcut QAGroupName
#endif
#if !FileExists(AppSource + "\Translation Studio.exe")
  #error AppSource must contain Translation Studio.exe
#endif
#if !FileExists(AppSource + "\translation-studio.install.ini")
  #error AppSource must contain the installer-owned empty marker file
#endif

[Setup]
AppId={#InstallerAppId}
AppName=치pdf
AppVersion={#AppVersion}
AppVerName=치pdf {#AppVersion}
AppPublisher=치pdf
AppComments=카드와 PDF를 번역하고 편집하는 데스크톱 프로그램
VersionInfoVersion={#AppVersion}
VersionInfoDescription=치pdf 설치 프로그램
VersionInfoProductName=치pdf
VersionInfoProductVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\{#InstallerGroup}
DefaultGroupName={#InstallerGroup}
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousTasks=yes
AllowNoIcons=no
AllowRootDirectory=no
AllowNetworkDrive=no
AllowUNCPath=no
AppendDefaultDirName=yes
PrivilegesRequired=lowest
SetupArchitecture=x64
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
; Qt 6.10 supports Windows 10 version 1809 (build 17763) and later.
MinVersion=10.0.17763
AppMutex={#InstallerMutex}
SetupMutex={#InstallerMutex}.Setup
CloseApplications=no
RestartApplications=no
RestartIfNeededByRun=no
AlwaysRestart=no
UninstallRestartComputer=no
CreateUninstallRegKey=yes
UninstallDisplayName={#InstallerDisplayName}
UninstallDisplayIcon={app}\Translation Studio.exe
UninstallLogMode=append
WizardStyle=modern
DisableWelcomePage=no
SetupLogging=yes
OutputDir={#OutputDir}
OutputBaseFilename=치pdf-{#AppVersion}-Setup
#if FileExists(AppSource + "\_internal\assets\chipdf.ico")
SetupIconFile={#AppSource}\_internal\assets\chipdf.ico
#endif
Compression=lzma2/fast
SolidCompression=yes
CompressionThreads=2

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Messages]
korean.WelcomeLabel2=카드와 PDF를 번역하고 편집하는 치pdf를 설치합니다.%n%n기본 번역은 설치된 Chrome의 내장 번역을 사용합니다. 오프라인 번역 모델은 별도 팩으로 추가할 수 있습니다.%n%n기존 작품(.twproj), 자동 저장·백업·서식과 이미 설치된 오프라인 모델은 유지됩니다.%n%n계속하기 전에 실행 중인 치pdf를 닫아 주세요.
korean.FinishedLabel=치pdf 설치를 마쳤습니다.%n%n시작 메뉴에서 프로그램을 실행할 수 있습니다. 저장한 작품과 기존 설정은 그대로 사용할 수 있습니다.
korean.ConfirmUninstall=치pdf 프로그램을 제거하시겠습니까?%n%n저장한 작품(.twproj), 자동 저장과 백업, 저장한 서식은 삭제하지 않습니다.
korean.UninstalledAll=치pdf 프로그램을 제거했습니다.%n%n저장한 작품과 사용자 데이터는 유지했습니다. 다시 설치하면 계속 사용할 수 있습니다.

[CustomMessages]
korean.DesktopShortcut=바탕 화면에 바로 가기 만들기
korean.LaunchProgram=치pdf 실행
korean.DataPreserved=저장한 작품과 사용자 데이터는 업데이트하거나 제거해도 유지됩니다.
korean.DataDirectory=자동 저장·백업·서식 저장 위치:
korean.UnsafeDirectory=프로그램 전용 폴더를 선택해 주세요. 드라이브나 사용자 폴더, 문서 폴더 자체, 사용자 데이터 폴더에는 설치할 수 없습니다.
korean.LinkedDirectory=연결된 폴더(정션 또는 심볼릭 링크)에는 설치할 수 없습니다. 실제 프로그램 전용 폴더를 선택해 주세요.
korean.UnownedDirectory=선택한 폴더에 다른 파일이 있습니다. 비어 있는 새 폴더 또는 기존 치pdf 설치 폴더를 선택해 주세요.
korean.UnreadableDirectory=선택한 폴더를 확인할 수 없습니다. 읽고 쓸 수 있는 프로그램 전용 폴더를 선택해 주세요.
korean.InvalidVersion=기존 설치 버전을 확인할 수 없어 업데이트를 중단했습니다. 기존 프로그램과 작업 파일은 변경하지 않았습니다.
korean.DowngradeBlocked=이미 더 최신 버전(%1)이 설치되어 있습니다. 이 설치 프로그램(%2)으로 이전 버전을 덮어쓸 수 없습니다. 기존 프로그램과 작업 파일은 변경하지 않았습니다.
korean.ApplicationRunning=치pdf가 실행 중입니다. 작업을 저장하고 프로그램을 닫은 뒤 다시 설치해 주세요.
korean.UpdateLocationChanged=기존 설치 위치에서 업데이트해 주세요:%n%1%n%n설치 위치를 바꾸려면 기존 프로그램을 제거한 뒤 다시 설치해 주세요. 저장한 작품과 사용자 데이터는 유지됩니다.
korean.InvalidInstallLocation=기존 설치 위치를 확인할 수 없어 업데이트를 중단했습니다. Windows 설정에서 기존 프로그램을 제거한 뒤 다시 설치해 주세요. 저장한 작품과 사용자 데이터는 유지됩니다.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked

[Files]
; All files come from the build wrapper's verified staging directory.
; No external files, user data, or project archives are registered for removal.
Source: "{#AppSource}\*"; DestDir: "{app}"; Excludes: "*.twproj,*.twproj.bak,*.tmp,translation-studio.install.ini"; Flags: ignoreversion recursesubdirs createallsubdirs
; Keep this tiny ownership record so reinstall can safely accept a directory
; containing projects the user added after installation. No project is adopted.
Source: "{#AppSource}\translation-studio.install.ini"; DestDir: "{app}"; Flags: ignoreversion uninsneveruninstall

[INI]
; This installer-owned identity record also remains after uninstallation.
Filename: "{app}\translation-studio.install.ini"; Section: "Installation"; Key: "AppId"; String: "{#InstallerAppId}"
Filename: "{app}\translation-studio.install.ini"; Section: "Installation"; Key: "Version"; String: "{#AppVersion}"
Filename: "{app}\translation-studio.install.ini"; Section: "Installation"; Key: "BuildId"; String: "{#BuildId}"
Filename: "{app}\translation-studio.install.ini"; Section: "Installation"; Key: "MutexName"; String: "{#InstallerMutex}"

[Icons]
Name: "{group}\{#InstallerShortcut}"; Filename: "{app}\Translation Studio.exe"; WorkingDir: "{app}"; AppUserModelID: "{#InstallerMutex}"
Name: "{autodesktop}\{#InstallerShortcut}"; Filename: "{app}\Translation Studio.exe"; WorkingDir: "{app}"; AppUserModelID: "{#InstallerMutex}"; Tasks: desktopicon

[Run]
Filename: "{app}\Translation Studio.exe"; Description: "{cm:LaunchProgram}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#InstallerAppId}_is1';
  MarkerName = 'translation-studio.install.ini';

function GetFileAttributesW(lpFileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function NormalPath(const Value: String): String;
begin
  Result := Lowercase(RemoveBackslashUnlessRoot(ExpandFileName(Trim(Value))));
end;

function SameOrBelow(const Candidate, Parent: String): Boolean;
var
  C, P: String;
begin
  C := NormalPath(Candidate);
  P := NormalPath(Parent);
  Result := (C = P) or (Pos(AddBackslash(P), C) = 1);
end;

#ifndef QAAppId
procedure RemoveOwnedLegacyShortcut(const ShortcutPath: String);
var
  Shell, Shortcut: Variant;
  TargetPath: String;
begin
  if not FileExists(ShortcutPath) then
    Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(ShortcutPath);
    TargetPath := Shortcut.TargetPath;
    { Only retire the exact legacy link when it still points to this install.
      A user-created or repointed shortcut with the same name is preserved. }
    if (TargetPath <> '') and
       (NormalPath(TargetPath) = NormalPath(ExpandConstant('{app}\Translation Studio.exe'))) then
      if not DeleteFile(ShortcutPath) then
        Log('Could not remove the legacy application shortcut: ' + ShortcutPath);
  except
    Log('Preserved legacy shortcut because its target could not be read: ' + ShortcutPath);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    RemoveOwnedLegacyShortcut(ExpandConstant('{group}\Translation Studio.lnk'));
    if WizardIsTaskSelected('desktopicon') then
      RemoveOwnedLegacyShortcut(ExpandConstant('{autodesktop}\Translation Studio.lnk'));
  end;
end;
#endif

function ContainsProtectedFolder(const Candidate, ProtectedPath: String): Boolean;
begin
  Result := SameOrBelow(ProtectedPath, Candidate);
end;

function HasLinkedAncestor(const Directory: String): Boolean;
var
  Current, Parent: String;
  Attributes: LongWord;
begin
  Result := False;
  Current := NormalPath(Directory);
  repeat
    Attributes := GetFileAttributesW(Current);
    if (Attributes <> $FFFFFFFF) and
       ((Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0) then begin
      Result := True;
      Exit;
    end;
    Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Current));
    if (Parent = '') or (CompareText(Parent, Current) = 0) then
      Exit;
    Current := Parent;
  until False;
end;

function HasLinkedDescendant(const Directory: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Directory) + '*', FindRec) then begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          if (FindRec.Attributes and FILE_ATTRIBUTE_REPARSE_POINT) <> 0 then begin
            Result := True;
            Exit;
          end;
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then begin
            if HasLinkedDescendant(AddBackslash(Directory) + FindRec.Name) then begin
              Result := True;
              Exit;
            end;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function CheckVersion(const InstalledVersion: String): String;
var
  Installed, Incoming: Int64;
begin
  Result := '';
  if InstalledVersion = '' then
    Exit;
  if not StrToVersion(InstalledVersion, Installed) or
     not StrToVersion('{#AppVersion}', Incoming) then begin
    Result := CustomMessage('InvalidVersion');
    Log('Translation Studio refused: installed version is invalid: ' + InstalledVersion);
    Exit;
  end;
  if ComparePackedVersion(Installed, Incoming) > 0 then begin
    Result := FmtMessage(CustomMessage('DowngradeBlocked'), [InstalledVersion, '{#AppVersion}']);
    Log('Translation Studio refused downgrade: installed=' + InstalledVersion + ', incoming={#AppVersion}');
  end;
end;

function CheckRegisteredVersion: String;
var
  InstalledVersion: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU64, UninstallKey, 'DisplayVersion', InstalledVersion) then
    Result := CheckVersion(InstalledVersion);
end;

function ValidateDirectory(const Directory: String): String;
var
  Target, Marker, StoredIdentity, StoredVersion, RegisteredPath, UserProfilePath: String;
  FindRec: TFindRec;
  Nonempty: Boolean;
begin
  Result := '';
  Target := NormalPath(Directory);
  { Inno has no userprofile shell constant. Resolve the Windows environment
    value explicitly and never normalize an empty value into the working dir. }
  UserProfilePath := Trim(GetEnv('USERPROFILE'));
  if UserProfilePath = '' then begin
    Result := CustomMessage('UnreadableDirectory');
    Log('Translation Studio refused: Windows USERPROFILE is missing.');
    Exit;
  end;
  if (Length(Target) < 4) or
     (Copy(Target, 1, 2) = '\\') or
     ContainsProtectedFolder(Target, UserProfilePath) or
     ContainsProtectedFolder(Target, ExpandConstant('{userdocs}')) or
     ContainsProtectedFolder(Target, ExpandConstant('{userdesktop}')) or
     ContainsProtectedFolder(Target, ExpandConstant('{localappdata}')) or
     ContainsProtectedFolder(Target, ExpandConstant('{userappdata}')) or
     SameOrBelow(Target, ExpandConstant('{localappdata}\TranslationStudio')) or
     SameOrBelow(Target, ExpandConstant('{win}')) or
     SameOrBelow(Target, ExpandConstant('{commonpf}')) then begin
    Result := CustomMessage('UnsafeDirectory');
    Log('Translation Studio refused protected installation directory: ' + Target);
    Exit;
  end;
  { A second directory with the same AppId would leave two uninstallers owning
    the same shortcuts and registry entry. Require uninstall before relocation. }
  if RegKeyExists(HKCU64, UninstallKey) then begin
    RegisteredPath := '';
    if not RegQueryStringValue(HKCU64, UninstallKey, 'InstallLocation', RegisteredPath) or
       (Trim(RegisteredPath) = '') then
      RegQueryStringValue(HKCU64, UninstallKey, 'Inno Setup: App Path', RegisteredPath);
    if Trim(RegisteredPath) = '' then begin
      Result := CustomMessage('InvalidInstallLocation');
      Log('Translation Studio refused update: registered installation directory is missing.');
      Exit;
    end;
    if Target <> NormalPath(RegisteredPath) then begin
      Result := FmtMessage(CustomMessage('UpdateLocationChanged'), [RegisteredPath]);
      Log('Translation Studio refused update to a different installation directory: registered=' +
        RegisteredPath + ', requested=' + Target);
      Exit;
    end;
  end;
  if HasLinkedAncestor(Target) then begin
    Result := CustomMessage('LinkedDirectory');
    Log('Translation Studio refused linked installation directory: ' + Target);
    Exit;
  end;
  if not DirExists(Target) then begin
    if FileExists(Target) then
      Result := CustomMessage('UnsafeDirectory');
    Exit;
  end;
  Nonempty := False;
  if FindFirst(AddBackslash(Target) + '*', FindRec) then begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then begin
          Nonempty := True;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end else begin
    Result := CustomMessage('UnreadableDirectory');
    Log('Translation Studio refused unreadable installation directory: ' + Target);
    Exit;
  end;
  if not Nonempty then
    Exit;
  if HasLinkedDescendant(Target) then begin
    Result := CustomMessage('LinkedDirectory');
    Log('Translation Studio refused installation directory containing a linked file or folder: ' + Target);
    Exit;
  end;
  Marker := AddBackslash(Target) + MarkerName;
  StoredIdentity := GetIniString('Installation', 'AppId', '', Marker);
  StoredVersion := GetIniString('Installation', 'Version', '', Marker);
  if (StoredIdentity <> '{#InstallerAppId}') or (StoredVersion = '') then begin
    Result := CustomMessage('UnownedDirectory');
    Log('Translation Studio refused nonempty unowned installation directory: ' + Target);
    Exit;
  end;
  Result := CheckVersion(StoredVersion);
end;

function InitializeSetup: Boolean;
var
  Error: String;
begin
  Error := CheckRegisteredVersion;
  Result := Error = '';
  if not Result then
    SuppressibleMsgBox(Error, mbError, MB_OK, IDOK);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Error: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Error := ValidateDirectory(WizardDirValue);
    Result := Error = '';
    if not Result then
      SuppressibleMsgBox(Error, mbError, MB_OK, IDOK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  NeedsRestart := False;
  Result := CheckRegisteredVersion;
  if Result <> '' then
    Exit;
  Result := ValidateDirectory(ExpandConstant('{app}'));
  if Result <> '' then
    Exit;
  if CheckForMutexes('{#InstallerMutex}') then begin
    Result := CustomMessage('ApplicationRunning');
    Log('Translation Studio refused: application mutex is present.');
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo,
  MemoTypeInfo, MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine + MemoGroupInfo;
  if MemoTasksInfo <> '' then
    Result := Result + NewLine + NewLine + MemoTasksInfo;
  Result := Result + NewLine + NewLine + CustomMessage('DataPreserved') +
    NewLine + CustomMessage('DataDirectory') + NewLine + Space +
    ExpandConstant('{localappdata}\TranslationStudio');
end;
