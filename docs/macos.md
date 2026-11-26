# macOS — OpsBoard reviewer setup

There are two routes. The native viewer uses Python's standard library and POSIX file permissions. The full Docker Blue/Green and Kubernetes GitOps supervisor is a Linux-oriented lab. Do not try to make it run by giving native Docker Desktop root privileges or replacing Linux-specific commands blindly.

## 1. Native browser viewer (Intel or Apple silicon)

Install [Python 3.14](https://www.python.org/downloads/) and Apple Command Line Tools (Git / Make). If the tools are missing, use `xcode-select --install` and complete Apple's prompt. With an existing Homebrew installation, `brew install python@3.14` is another Python option.

In macOS Terminal:

```bash
python3.14 --version
git clone https://github.com/Mishkaaass/ci-cd-lab.git
cd ci-cd-lab
unset OPSBOARD_SHOWCASE_DIR
make requirements
make setup
make viewer
```

Open http://127.0.0.1:18002/ and read the private Viewer token in another terminal:

```bash
cat "${XDG_CONFIG_HOME:-$HOME/.config}/ci-cd-lab/unified-console/viewer.token"
```

No Docker, third-party Python packages, sudo, or Kubernetes is required for this route. Optional Linux-tool warnings are normal. GitHub evidence may be unavailable without the optional authenticated GitHub CLI. Stop with Ctrl+C.

## 2. Full demo in Ubuntu

Create a dedicated Ubuntu VM using a trusted hypervisor, or use a dedicated Linux lab host that you control. Use a Linux x86-64 environment to match the reference app image and CI architecture; on Apple silicon, a native ARM guest may need a separately reviewed ARM-compatible application image, so a trusted x86-64 lab host is an alternative. Install the Linux guest's own Docker Engine, Compose, Python 3.14, kind and kubectl following [Linux setup](linux.md). Clone the repository in the guest's Linux filesystem and run `make requirements`, `make setup`, `make showcase` there.

Use the browser inside the guest. Alternatively, if you have SSH configured to that host, forward only the loopback console port from your Mac (replace the placeholder with your verified SSH destination):

```bash
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:18002:127.0.0.1:18002 USER@LAB_HOST
```

Verify the SSH host key through a trusted channel; do not disable host-key checking. Then open http://127.0.0.1:18002/ on the Mac. Read the guest's Viewer/Operator tokens in a separate guest terminal, and authorize drills in the original guest launcher terminal. Never expose the dashboard port publicly.

The Linux VM route keeps Linux permissions and tools intact. Native macOS full-demo support and all Intel/ARM combinations have not been runtime-certified. Do not delete state or relax security to work around compatibility errors.
