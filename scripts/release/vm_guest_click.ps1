param(
  [Parameter(Mandatory = $true)]
  [string[]]$Points,
  [int]$DelayMs = 250
)

$ErrorActionPreference = "Stop"

$parsedPoints = @()
foreach ($part in $Points) {
  foreach ($value in ($part -split ",")) {
    if ($value.Trim()) {
      $parsedPoints += [int]$value.Trim()
    }
  }
}

if (($parsedPoints.Count % 2) -ne 0) {
  throw "Points must be x,y pairs."
}

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class NativeMouse {
  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int X, int Y);

  [DllImport("user32.dll")]
  public static extern void mouse_event(int dwFlags, int dx, int dy, int dwData, UIntPtr dwExtraInfo);
}
"@

for ($i = 0; $i -lt $parsedPoints.Count; $i += 2) {
  $x = $parsedPoints[$i]
  $y = $parsedPoints[$i + 1]
  [NativeMouse]::SetCursorPos($x, $y) | Out-Null
  Start-Sleep -Milliseconds $DelayMs
  [NativeMouse]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [NativeMouse]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds $DelayMs
}
