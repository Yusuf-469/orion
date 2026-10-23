# ORION Stage 0 environment audit (read-only).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\env_audit.ps1 > artifacts\env_audit_raw.txt
# Queries system state only; installs and changes nothing.

function Section($name) { "`n===== $name =====" }
function Try-Run($label, [scriptblock]$block) {
    try { $out = & $block 2>&1 | Out-String; "[$label]`n$($out.TrimEnd())" }
    catch { "[$label] ERROR: $($_.Exception.Message)" }
}

"ORION env audit run at $(Get-Date -Format o)"

Section "OS"
Try-Run "os" { Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture | Format-List }

Section "CPU / RAM"
Try-Run "cpu" { Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed | Format-List }
Try-Run "ram_gb" { [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2) }

Section "Disk"
Try-Run "disk" { Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID, @{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}}, @{n='FreeGB';e={[math]::Round($_.FreeSpace/1GB,1)}} | Format-Table -AutoSize }

Section "GPU"
Try-Run "video_controllers" { Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM, VideoModeDescription | Format-List }
Try-Run "nvidia-smi" { nvidia-smi }
Try-Run "nvidia-smi query" { nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version,compute_cap --format=csv }
Try-Run "nvcc" { nvcc --version }

Section "Display"
Try-Run "screens" { Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Screen]::AllScreens | Select-Object DeviceName, Primary, Bounds | Format-List }
Try-Run "dpi_registry" { Get-ItemProperty 'HKCU:\Control Panel\Desktop' -Name LogPixels, Win8DpiScaling -ErrorAction SilentlyContinue | Select-Object LogPixels, Win8DpiScaling | Format-List }
Try-Run "per_monitor_scaling" { Get-ChildItem 'HKCU:\Control Panel\Desktop\PerMonitorSettings' -ErrorAction SilentlyContinue | ForEach-Object { "$($_.PSChildName): DpiValue=$((Get-ItemProperty $_.PSPath).DpiValue)" } }

Section "Toolchain"
Try-Run "py launcher" { py -0p }
Try-Run "python" { python --version; (Get-Command python -ErrorAction SilentlyContinue).Source }
Try-Run "pip" { python -m pip --version }
Try-Run "git" { git --version }
Try-Run "code" { code --version }
Try-Run "node" { node --version }
Try-Run "tesseract" { tesseract --version }

Section "Python packages"
Try-Run "pip list (filtered)" { python -m pip list 2>$null | Select-String -Pattern 'torch|cuda|playwright|pywinauto|uiautomation|pyside|pydantic|opencv|easyocr|paddle|pytesseract|scikit|numpy|transformers|pyinstaller|pytest' }
Try-Run "torch cuda" { python -c "import torch; print('torch', torch.__version__); print('cuda available', torch.cuda.is_available()); print('cuda build', torch.version.cuda); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)" }

"`nAudit complete."
