# Building the agent VM (Hyper-V)

A Windows 11 VM on your work laptop whose **only** job is running a second Claude
Desktop that Jarvis can drive. Budget 60–90 minutes, most of it Windows installing
itself.

## Before you start — the rules this VM lives by

1. **It never gets corporate credentials.** No Outlook, no OneDrive, no work SSO,
   no domain join. The only account it signs into is Claude. Everything work-related
   reaches it because Jarvis handed it over deliberately — which is also what keeps
   the audit story clean.
2. **It is not on the corporate LAN.** We give it an internal switch with NAT, so it
   has internet but is invisible to the work network. An External switch would put an
   unmanaged Windows box on your employer's network; don't.
3. **It is disposable.** Checkpoint it once it works. If it breaks, roll back.

> One thing to confirm early: if your Claude account is an **enterprise seat
> provisioned through work SSO**, signing in on a second machine may hit device
> policies. A personal Pro/Max account has no such problem. Find out which you have
> before building anything.

---

## 1. Prerequisites

Hyper-V needs **Windows 11 Pro, Enterprise, or Education** — it does not exist on
Home. Check, in an admin PowerShell:

```powershell
Get-ComputerInfo -Property WindowsProductName, CsTotalPhysicalMemory, HyperVRequirementVirtualizationFirmwareEnabled
```

You want ≥16GB physical RAM (we'll give the VM 8–12GB) and virtualization enabled in
firmware. If the virtualization line says `False`, reboot into UEFI and turn on
Intel VT-x / AMD-V.

## 2. Enable Hyper-V

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
```

Reboot when it asks.

## 3. Build the network first

Do this before the VM. We want a **fixed** address for the bridge, and the built-in
"Default Switch" reassigns its subnet on every host reboot — which would silently
break the connection between Jarvis and the VM every few days.

```powershell
# One internal switch, one NAT, one predictable subnet.
New-VMSwitch -SwitchName "JarvisNAT" -SwitchType Internal

$idx = (Get-NetAdapter -Name "vEthernet (JarvisNAT)").ifIndex
New-NetIPAddress -IPAddress 192.168.220.1 -PrefixLength 24 -InterfaceIndex $idx
New-NetNat -Name "JarvisNAT" -InternalIPInterfaceAddressPrefix 192.168.220.0/24
```

**Check for a conflict first** — Docker Desktop and WSL2 both create NATs, and Windows
allows only one NAT per prefix:

```powershell
Get-NetNat        # if something already owns an overlapping prefix, pick another /24
```

The host will be `192.168.220.1`. The VM will be `192.168.220.10`. Those two addresses
are the whole network story.

## 4. Create the VM

```powershell
$vm   = "Jarvis-Agent"
$disk = "C:\Hyper-V\$vm\$vm.vhdx"
$iso  = "C:\ISO\Win11.iso"          # download from Microsoft's site

New-VM -Name $vm -Generation 2 -MemoryStartupBytes 8GB `
       -NewVHDPath $disk -NewVHDSizeBytes 80GB -SwitchName "JarvisNAT"

Set-VMProcessor  -VMName $vm -Count 4
Set-VMMemory     -VMName $vm -DynamicMemoryEnabled $true -MinimumBytes 4GB -MaximumBytes 12GB

# Windows 11 refuses to install without TPM + Secure Boot.
Set-VMKeyProtector -VMName $vm -NewLocalKeyProtector
Enable-VMTPM       -VMName $vm
Set-VMFirmware     -VMName $vm -EnableSecureBoot On -SecureBootTemplate MicrosoftWindows

Add-VMDvdDrive     -VMName $vm -Path $iso
Set-VMFirmware     -VMName $vm -FirstBootDevice (Get-VMDvdDrive -VMName $vm)

# Survive host reboots without you.
Set-VM -Name $vm -AutomaticStartAction Start -AutomaticStartDelay 60 -AutomaticStopAction Save

Start-VM  -Name $vm
vmconnect.exe localhost $vm
```

**Sizing note:** 4 vCPU / 8–12GB dynamic is comfortable for one Electron app. Don't
give it more than half your physical RAM — your actual work still needs the machine.

## 5. Install Windows in the VM

Normal install, with two wrinkles:

- **Press a key fast** when it says "Press any key to boot from CD" or it falls
  through to a "no bootable device" screen. If that happens, `Set-VMFirmware`
  the DVD back to first and restart.
- **Local account.** Windows 11 setup pushes hard for a Microsoft account. At the
  network screen press `Shift+F10` and run `start ms-cxh:localonly` (recent builds)
  or `OOBE\BYPASSNRO` (older builds) to get a local account option. Either way, this
  machine should not be signed into your Microsoft identity.

Once at the desktop, install the guest tooling:

```powershell
# In the VM, admin PowerShell
Set-Service   -Name vmicguestinterface -StartupType Automatic -Status Running
```

## 6. Give the VM its static address

In the VM, admin PowerShell:

```powershell
$idx = (Get-NetAdapter).ifIndex
New-NetIPAddress -InterfaceIndex $idx -IPAddress 192.168.220.10 -PrefixLength 24 -DefaultGateway 192.168.220.1
Set-DnsClientServerAddress -InterfaceIndex $idx -ServerAddresses 1.1.1.1,8.8.8.8
```

Confirm it works both ways:

```powershell
Test-NetConnection 192.168.220.1     # VM -> host
ping www.anthropic.com               # VM -> internet
```

## 7. Stop the VM locking itself

This matters more than it sounds. Closing the VMConnect window does **not** lock or
suspend the guest — the guest never learns you looked away, which is exactly why this
beats RDP for automation. But a screensaver or lock policy *inside* the guest will
still lock it, and UI Automation cannot drive a locked desktop.

In the VM:

```powershell
powercfg /change monitor-timeout-ac 0
powercfg /change standby-timeout-ac 0
reg add "HKCU\Control Panel\Desktop" /v ScreenSaveActive /t REG_SZ /d 0 /f
```

Then set auto-login (Settings → Accounts → Sign-in options → turn off "require
sign-in"), or use Sysinternals **Autologon**, which stores the credential in LSA
rather than the registry in the clear. This VM holds a Claude session and nothing
else, which is what makes auto-login an acceptable trade here.

## 8. Install Claude Desktop and sign in

Download Claude Desktop in the VM, install, sign in, and **leave it running**.
Open it once manually and send a message so the account is fully initialised.

## 9. Install the bridge

```powershell
# In the VM
winget install Python.Python.3.12 Git.Git
git clone <your-repo-url> C:\jarvis-at-work
cd C:\jarvis-at-work
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
Copy-Item config.agent.example.yaml config.agent.yaml
```

Generate a token and put it in `config.agent.yaml` under `bridge.token` — you'll
paste the same value into the laptop's `config.yaml` later:

```powershell
python -c "import secrets;print(secrets.token_urlsafe(32))"
```

## 10. Run the spike — this is the real milestone

Everything above is plumbing. **This** is the step that decides whether the plan
works:

```powershell
.\.venv\Scripts\python -m jarvis_work.agent.spike_uia --depth 12 --write "hello from jarvis"
```

Read the VERDICT at the bottom:

- **RICH** — UIA driving works. Paste the printed `composer_automation_id` /
  `composer_name` into `config.agent.yaml` and carry on.
- **THIN** — workable but fragile. Retry with `--depth 16` before concluding.
- **EMPTY** — Chromium hasn't built its accessibility tree. Quit Claude and relaunch
  it once as `Claude.exe --force-renderer-accessibility`, then rerun the spike.

Also note what the write test says about **focus**. If `ValuePattern` accepted the
text without focus, Jarvis can work while you use the VM for other things. If it
needed focus, the VM becomes single-purpose — still fine, just worth knowing.

**Send me the spike output** and I'll tune the selectors.

## 11. Open the firewall to the host only

```powershell
New-NetFirewallRule -DisplayName "Jarvis bridge" -Direction Inbound -Protocol TCP `
  -LocalPort 8766 -RemoteAddress 192.168.220.1 -Action Allow
```

`-RemoteAddress` is the point of that rule — only the host may connect.

## 12. Start the bridge, and keep it started

```powershell
.\.venv\Scripts\python -m jarvis_work.agent.uia_bridge
```

From the **host**, confirm it answers:

```powershell
curl.exe http://192.168.220.10:8766/health
```

Then make it permanent with Task Scheduler in the VM: trigger *At log on*, action
`C:\jarvis-at-work\.venv\Scripts\pythonw.exe -m jarvis_work.agent.uia_bridge`,
start-in `C:\jarvis-at-work`, and **do not** tick "run whether user is logged on or
not" — UI Automation needs a real interactive session.

## 13. Checkpoint

```powershell
Checkpoint-VM -Name "Jarvis-Agent" -SnapshotName "clean-claude-bridge-working"
```

Take it the moment everything works. Claude Desktop updates itself, and one day an
update will move the composer control; rolling back to a known-good VM while you
rerun the spike beats debugging under pressure.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `New-NetNat` fails | Docker/WSL2 owns an overlapping prefix | `Get-NetNat`, pick a different /24 |
| VM has no internet | NAT not created, or wrong gateway | Re-check step 3, confirm gateway is `192.168.220.1` |
| Host can't reach `:8766` | Guest firewall | Step 11; confirm the bridge is bound to `0.0.0.0` |
| Bridge returns 401 | Token mismatch | `bridge.token` (VM) must equal `agent.bridge_token` (laptop) |
| Bridge returns 503 | Claude not running, or window not found | Start Claude in the VM; rerun the spike |
| Spike finds an empty tree | Chromium a11y not initialised | Relaunch with `--force-renderer-accessibility` |
| Everything broke after an update | Claude moved its controls | Roll back to the checkpoint, rerun the spike, update config |
| VM IP changed | You used Default Switch, not JarvisNAT | Reattach the VM to `JarvisNAT` |
