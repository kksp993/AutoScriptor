param(
  [string]$LabRoot = "C:\AutoScriptorReleaseLab",
  [switch]$Json
)

$ErrorActionPreference = "SilentlyContinue"

function CommandPath([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  if ($Name -eq "VBoxManage") {
    $fallback = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
    if (Test-Path -LiteralPath $fallback -PathType Leaf) { return $fallback }
  }
  return $null
}

function FeatureState([string]$Name) {
  try {
    $f = Get-WindowsOptionalFeature -Online -FeatureName $Name -ErrorAction Stop
    return [string]$f.State
  } catch {
    return "Unavailable"
  }
}

$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$computer = Get-ComputerInfo
$volumes = Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter,FileSystemLabel,SizeRemaining,Size
$tools = [ordered]@{
  VBoxManage = CommandPath "VBoxManage"
  VMwareRun = CommandPath "vmrun"
  Qemu = CommandPath "qemu-system-x86_64"
  Choco = CommandPath "choco"
  Winget = CommandPath "winget"
}

$result = [ordered]@{
  Host = [ordered]@{
    WindowsProductName = $computer.WindowsProductName
    WindowsVersion = $computer.WindowsVersion
    HyperVisorPresent = $computer.HyperVisorPresent
    MemoryGB = [math]::Round($computer.CsTotalPhysicalMemory / 1GB, 2)
    LogicalProcessors = $computer.CsNumberOfLogicalProcessors
  }
  Cpu = [ordered]@{
    Name = $cpu.Name
    Cores = $cpu.NumberOfCores
    LogicalProcessors = $cpu.NumberOfLogicalProcessors
    VirtualizationFirmwareEnabled = $cpu.VirtualizationFirmwareEnabled
    SecondLevelAddressTranslationExtensions = $cpu.SecondLevelAddressTranslationExtensions
    VMMonitorModeExtensions = $cpu.VMMonitorModeExtensions
  }
  WindowsFeatures = [ordered]@{
    HyperV = FeatureState "Microsoft-Hyper-V-All"
    VirtualMachinePlatform = FeatureState "VirtualMachinePlatform"
    WSL = FeatureState "Microsoft-Windows-Subsystem-Linux"
  }
  Tools = $tools
  Volumes = $volumes
  LabRoot = $LabRoot
  Recommendations = @()
}

if (-not $tools.VBoxManage -and -not $tools.VMwareRun -and -not $tools.Qemu) {
  $result.Recommendations += "No VM manager detected. Install VirtualBox or VMware Workstation before creating a lab VM."
}
if (-not $tools.Choco -and -not $tools.Winget) {
  $result.Recommendations += "No package manager detected. Download the VM manager installer manually from the vendor site."
}
if ($computer.CsTotalPhysicalMemory -lt 16GB) {
  $result.Recommendations += "Host memory is low for Windows VM testing; 16GB+ is recommended."
}
if (-not (Test-Path $LabRoot)) {
  $result.Recommendations += "Lab root does not exist yet; the create script will make it."
}

if ($Json) {
  $result | ConvertTo-Json -Depth 6
} else {
  $result | Format-List
  ""
  "Tools:"
  $tools.GetEnumerator() | ForEach-Object { "  {0}: {1}" -f $_.Key, ($(if ($_.Value) { $_.Value } else { "<missing>" })) }
  ""
  "Volumes:"
  $volumes | Format-Table -AutoSize
  ""
  "Recommendations:"
  if ($result.Recommendations.Count) {
    $result.Recommendations | ForEach-Object { "  - $_" }
  } else {
    "  - Host looks ready for a VM lab."
  }
}
