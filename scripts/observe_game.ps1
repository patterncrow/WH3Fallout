# 历史诊断工具，保留用于追溯；按当前约定不自动执行游戏界面操作。
param(
    [Parameter(Mandatory=$true)][int]$GameProcessId,
    [Parameter(Mandatory=$true)][string]$CapturePath,
    [int]$ClickX = -1,
    [int]$ClickY = -1
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System; using System.Runtime.InteropServices;
public static class FnvtwGameUi {
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
 [StructLayout(LayoutKind.Sequential)] public struct Point { public int X,Y; }
 [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h,ref Point point);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out Rect rect);
 [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h,out Rect rect);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int command);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags,uint x,uint y,uint data,UIntPtr extra);
}
'@
$game = Get-Process -Id $GameProcessId
if ($game.ProcessName -ne 'Warhammer3') { throw 'Target process must be Warhammer3' }
$handle = $game.MainWindowHandle
if ($handle -eq [IntPtr]::Zero) { throw 'Game window is not available' }
[FnvtwGameUi]::ShowWindow($handle,9) | Out-Null
[FnvtwGameUi]::SetForegroundWindow($handle) | Out-Null
Start-Sleep -Milliseconds 250
if ([FnvtwGameUi]::GetForegroundWindow() -ne $handle) { throw 'Game does not have focus; no input sent' }
if ($ClickX -ge 0 -and $ClickY -ge 0) {
    # 输入只发送到已确认在前台的本次游戏窗口，不操作其他程序。
    $client = New-Object FnvtwGameUi+Rect
    [FnvtwGameUi]::GetClientRect($handle,[ref]$client) | Out-Null
    if ($ClickX -ge $client.Right -or $ClickY -ge $client.Bottom) { throw 'Click lies outside the game client' }
    $point = New-Object FnvtwGameUi+Point
    $point.X=$ClickX; $point.Y=$ClickY
    [FnvtwGameUi]::ClientToScreen($handle,[ref]$point) | Out-Null
    [FnvtwGameUi]::SetCursorPos($point.X,$point.Y) | Out-Null
    [FnvtwGameUi]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    [FnvtwGameUi]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 900
}
if ([FnvtwGameUi]::GetForegroundWindow() -ne $handle) { throw 'Game lost focus; no desktop capture performed' }
$rect = New-Object FnvtwGameUi+Rect
[FnvtwGameUi]::GetWindowRect($handle,[ref]$rect) | Out-Null
$bitmap = New-Object Drawing.Bitmap(($rect.Right-$rect.Left),($rect.Bottom-$rect.Top))
$graphics = [Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($rect.Left,$rect.Top,0,0,$bitmap.Size)
    $bitmap.Save([IO.Path]::GetFullPath($CapturePath),[Drawing.Imaging.ImageFormat]::Png)
} finally { $graphics.Dispose(); $bitmap.Dispose() }
