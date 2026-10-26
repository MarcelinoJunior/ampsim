; Instalador do AmpSim (Inno Setup 6). Monte com: python tools/instalador/montar.py
; Recebe do montar.py: AmpVer (ex.: 1.0.0-beta), AmpDist (pasta do PyInstaller), AmpRaiz (repositório), AmpSaida.

#ifndef AmpVer
  #define AmpVer "0.0.0"
#endif

[Setup]
AppId={{6B1C2E4A-8F3D-4A57-9C1E-3A5D7F9B2C41}
AppName=AmpSim
AppVersion={#AmpVer}
AppVerName=AmpSim {#AmpVer}
AppPublisher=Marcelino (AmpSim)
AppPublisherURL=https://github.com/MarcelinoJunior/ampsim
AppSupportURL=https://github.com/MarcelinoJunior/ampsim
DefaultDirName={localappdata}\Programs\AmpSim
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#AmpSaida}
OutputBaseFilename=AmpSim-Setup-{#AmpVer}
SetupIconFile={#AmpRaiz}\assets\ampsim.ico
UninstallDisplayIcon={app}\AmpSim.exe
LicenseFile={#AmpRaiz}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "pianos"; Description: "Baixar agora os pianos gravados (também dá para baixar depois, na tela Timbres adicionais do AmpSim):"; GroupDescription: "Timbres adicionais:"
Name: "pianos\upright"; Description: "Piano de Armário (Upright KW) · 44 MB"
Name: "pianos\ydp"; Description: "Piano de Cauda YDP (Yamaha Disklavier) · 52 MB"
Name: "pianos\salamander"; Description: "Piano de Cauda Salamander (Yamaha C5) · 296 MB (ocupa 1,3 GB)"; Flags: unchecked
Name: "flexasio"; Description: "FlexASIO (driver ASIO gratuito de código aberto; baixa do GitHub oficial)"; GroupDescription: "Drivers de áudio (só se a sua placa não tiver driver ASIO próprio):"; Flags: unchecked
Name: "asio4all"; Description: "ASIO4ALL 2.22 (baixa do site oficial asio4all.org)"; GroupDescription: "Drivers de áudio (só se a sua placa não tiver driver ASIO próprio):"; Flags: unchecked

[Files]
Source: "{#AmpDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AmpSim"; Filename: "{app}\AmpSim.exe"
Name: "{autodesktop}\AmpSim"; Filename: "{app}\AmpSim.exe"; Tasks: atalho

[Run]
; compila o áudio (Numba) agora, para a 1ª abertura não demorar ~1 minuto
Filename: "{app}\AmpSim.exe"; Parameters: "--selftest ""{app}\instalacao.txt"""; StatusMsg: "Preparando o AmpSim (compila o áudio, cerca de 1 minuto)…"; Flags: runhidden waituntilterminated
Filename: "{app}\AmpSim.exe"; Description: "Abrir o AmpSim"; Flags: nowait postinstall skipifsilent
; atualização silenciosa (pelo próprio AmpSim): abre de novo no fim
Filename: "{app}\AmpSim.exe"; Flags: nowait; Check: ReopenAfterSilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_timbres"
Type: files; Name: "{app}\instalacao.txt"
Type: filesandordirs; Name: "{app}\_internal\ampsim"

[Code]
var
  DownloadPage: TDownloadWizardPage;

{ atualização silenciosa feita pelo AmpSim: abre de novo no fim (/NOABRIR=1 não abre: testes) }
function ReopenAfterSilent: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:NOABRIR|0}') <> '1');
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), 'Baixando os itens escolhidos…', @OnDownloadProgress);
end;

var
  Wanted: Integer;

procedure AddIf(const Task, Url, Name, Sha: String);
begin
  if WizardIsTaskSelected(Task) then begin
    DownloadPage.Add(Url, Name, Sha);
    Wanted := Wanted + 1;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpReady then begin
    DownloadPage.Clear;
    Wanted := 0;
    AddIf('pianos\upright', 'https://github.com/MarcelinoJunior/ampsim/releases/download/timbres-pianos-1/piano-upright.zip', 'piano-upright.zip', 'dc44e338cd4055243596dfec2d96d359daabeae30de4228ab8d1952249ece2f6');
    AddIf('pianos\ydp', 'https://github.com/MarcelinoJunior/ampsim/releases/download/timbres-pianos-1/piano-ydp.zip', 'piano-ydp.zip', 'ee32495a5f923215e2dc3606dce6594c58bc18ae403501d59ed54bfd2ebcbe0e');
    AddIf('pianos\salamander', 'https://github.com/MarcelinoJunior/ampsim/releases/download/timbres-pianos-1/piano-salamander.tar.xz', 'piano-salamander.tar.xz', '15edb061d7ba60d58332f72dba8f8ce40988048cc703f935e6320f37d650e213');
    AddIf('flexasio', 'https://github.com/dechamps/FlexASIO/releases/download/flexasio-1.10b/FlexASIO-1.10b.exe', 'FlexASIO-1.10b.exe', 'fe496bcc08d6c421c6244c8a60ac7b538560bda138000fd1a54ab8ebce031209');
    AddIf('asio4all', 'https://asio4all.org/downloads/ASIO4ALL_2_22.exe', 'ASIO4ALL_2_22.exe', '0d4f0c63bf5df077e4c74f18372f72b8e875a9abea499fea78aaa9f56022ac7e');
    if Wanted = 0 then
      Exit;
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if DownloadPage.AbortedByUser then
          Log('Download cancelado.')
        else
          SuppressibleMsgBox('Não foi possível baixar algum item (sem internet?). O AmpSim é instalado mesmo assim; ' +
            'os pianos podem ser baixados depois na tela Timbres adicionais.' + #13#10#13#10 + AddPeriod(GetExceptionMessage),
            mbError, MB_OK, IDOK);
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure MovePack(const Name: String);
begin
  if FileExists(ExpandConstant('{tmp}\' + Name)) then begin
    ForceDirectories(ExpandConstant('{app}\_timbres'));
    if not RenameFile(ExpandConstant('{tmp}\' + Name), ExpandConstant('{app}\_timbres\' + Name)) then
      CopyFile(ExpandConstant('{tmp}\' + Name), ExpandConstant('{app}\_timbres\' + Name), False);
  end;
end;

procedure RunDriver(const Name: String);
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{tmp}\' + Name)) then
    ShellExec('', ExpandConstant('{tmp}\' + Name), '', '', SW_SHOW, ewWaitUntilTerminated, Code);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    { o AmpSim instala os pianos na 1ª abertura, com barra de progresso }
    MovePack('piano-upright.zip');
    MovePack('piano-ydp.zip');
    MovePack('piano-salamander.tar.xz');
    { os drivers têm o próprio instalador (pedem permissão de administrador) }
    RunDriver('FlexASIO-1.10b.exe');
    RunDriver('ASIO4ALL_2_22.exe');
  end;
end;
