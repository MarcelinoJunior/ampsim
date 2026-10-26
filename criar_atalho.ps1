# Cria (ou recria) o atalho "AmpSim" na Área de Trabalho apontando para esta pasta.
# Uso: clique com o botão direito > "Executar com o PowerShell", ou:
#   powershell -ExecutionPolicy Bypass -File criar_atalho.ps1
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desktop 'AmpSim.lnk'))
$lnk.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
$lnk.Arguments = '/c "' + (Join-Path $root 'run.bat') + '"'
$lnk.WorkingDirectory = $root
$lnk.IconLocation = (Join-Path $root 'assets\ampsim.ico') + ',0'
$lnk.WindowStyle = 7          # minimizado: o console só aparece na barra durante a 1a instalação
$lnk.Description = 'AmpSim - simulador de amp para guitarra, baixo e pads'
$lnk.Save()

# Mesma identidade que o AmpSim usa na barra de tarefas ("AmpSim.App", ver ampsim/__main__.py):
# assim o Windows mostra o ícone do atalho na janela e "Fixar na barra de tarefas" abre o AmpSim.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    [PreserveSig] int GetCount(out uint count);
    [PreserveSig] int GetAt(uint index, out PropKey key);
    [PreserveSig] int GetValue(ref PropKey key, out PropVar value);
    [PreserveSig] int SetValue(ref PropKey key, ref PropVar value);
    [PreserveSig] int Commit();
}
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PropKey { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit, Size = 16)]
public struct PropVar { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
public static class AmpSimLnk {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr bc, int flags, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
    public static int SetAppId(string path, string appId) {
        Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore store;
        SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref iid, out store);   // 2 = leitura e escrita
        PropKey key = new PropKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        PropVar v = new PropVar { vt = 31, p = Marshal.StringToCoTaskMemUni(appId) };      // 31 = texto
        int hr = store.SetValue(ref key, ref v);
        if (hr == 0) hr = store.Commit();
        Marshal.FreeCoTaskMem(v.p);
        Marshal.ReleaseComObject(store);
        return hr;
    }
}
'@
$hr = [AmpSimLnk]::SetAppId((Join-Path $desktop 'AmpSim.lnk'), 'AmpSim.App')
if ($hr -ne 0) { Write-Host "Aviso: não deu para gravar a identidade do atalho (código $hr)" }
Write-Host "Atalho criado em $(Join-Path $desktop 'AmpSim.lnk')"
