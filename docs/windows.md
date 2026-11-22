# Run OpsBoard on Windows (WSL 2)

OpsBoard uses Linux containers and Bash. **Windows runs the same real lab through Ubuntu WSL 2**, not as a native Windows container application. The PowerShell launcher installs nothing into Windows automatically and never asks for a password in the browser.

## First-time setup

1. Use a supported Windows 11 or Windows 10 PC with hardware virtualization, **8 GB RAM minimum** (16 GB recommended for the full kind cluster).
2. If Ubuntu WSL 2 is missing, open **PowerShell as Administrator** and run `wsl --install -d Ubuntu`. Restart if Windows requests it. Open **Ubuntu** once from Start, create your Linux username and password, then close it. Verify `wsl -l -v` shows version **2** for Ubuntu. [Microsoft setup](https://learn.microsoft.com/en-us/windows/wsl/install).
3. Install and start [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/). Select **Linux containers** and the **WSL 2** backend. Under **Settings → Resources → WSL Integration**, enable your Ubuntu distribution and select **Apply & Restart**. [Docker's WSL guide](https://docs.docker.com/desktop/features/wsl/).
4. Get this repository from GitHub using **Code → Download ZIP → Extract All**, or use Git for Windows and `git clone https://github.com/Mishkaaass/ci-cd-lab.git`.

## Launch (Windows PowerShell)

Open PowerShell in the extracted / cloned `ci-cd-lab` directory, and run **one command**:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-showcase.ps1
```

If your WSL Ubuntu is named something like `Ubuntu-24.04` and is **not** the default WSL distribution, specify it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-showcase.ps1 -Distribution Ubuntu-24.04
```

On first use, the launcher checks Docker Desktop and asks before installing missing Ubuntu packages. It installs Python 3.14 **for your WSL user only** (without changing system Python), and downloads checksum-verified `kind` and `kubectl` to `~/.local/bin`. It clones the project into **Ubuntu's filesystem** for reliable Linux file permissions and Docker mounts. The first run can take considerably longer than five minutes.

Leave PowerShell open. When the terminal prints `READY`, open **http://127.0.0.1:18002/** in your **Windows browser**. To view the local Viewer token, open a second PowerShell window and run:

```powershell
wsl.exe --exec sh -lc 'cat ~/.config/ci-cd-lab/unified-console/viewer.token'
```

When using `-Distribution`, add `-d Ubuntu-24.04` after `wsl.exe` in that command too. Do **not** paste the token into issues, screenshots or chat. In the browser, click **Live Demo → Run full showcase** to watch verified Docker Blue/Green promotion, rollback and Kubernetes GitOps reconciliation.

If Ubuntu asks for `sudo`, type the **Ubuntu/Linux password in PowerShell**; no characters appear as you type. Do not enter a password on the OpsBoard website.

## What to expect, and what it does not do

- The dashboard is local-only. No Kubernetes cluster or Docker daemon is hosted by this website.
- All commands run **inside Ubuntu WSL 2**; Docker commands use the **Docker Desktop Linux engine**. Do not install a second Docker Engine inside WSL.
- The first launch may download container images and create the dedicated `kind-opsboard-review` cluster; this consumes local resources and disk space. It does not use AWS.
- Stop the foreground launcher with `Ctrl+C`. Docker volumes and the local Kubernetes PersistentVolumeClaim are **preserved**, not deleted.
- GitHub CLI login inside Ubuntu is **optional** for detailed CI job results (`gh auth login`). If not connected, the Security tab can truthfully show **Unavailable** rather than invent a pass.
- Native Windows Docker containers, Git Bash without WSL, and direct public Internet exposure are **not** supported.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `WSL/Ubuntu is not ready` | Run `wsl --install -d Ubuntu` once in Admin PowerShell, reboot, and create the Ubuntu user. |
| `Docker Desktop ... integration` | Start Docker Desktop, enable its WSL 2 engine and Ubuntu integration, and select Linux containers. |
| `WSL 2 required` | Run `wsl -l -v`. If Ubuntu is version 1, see [Microsoft's WSL 2 conversion instructions](https://learn.microsoft.com/en-us/windows/wsl/basic-commands). |
| `Could not clone repository` | Use a Git checkout instead of ZIP if GitHub requires authentication; keep the code in Ubuntu's filesystem. |
| Browser cannot reach `18002` | Confirm `READY` appears and WSL is running. Open `http://127.0.0.1:18002/` (not `https`). Check VPN/firewall policies if localhost forwarding is blocked. |
| GitOps does not become ready | Open Docker Desktop's resource settings and check RAM availability; review the error in the PowerShell/Ubuntu terminal. |

**Security note:** The launcher deliberately does not turn on virtualization, install Docker Desktop, loosen PowerShell execution policy globally, add users to the Docker group, delete volumes, or expose ports to the public network. Docker Desktop access is a privileged local capability; run only on a trusted PC. Docker Desktop commercial licensing conditions may apply within larger organizations.
