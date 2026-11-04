#!/usr/bin/env bash
# One-time setup on Ubuntu 22.04 / 24.04 (VirtualBox VM is fine).
# Installs Docker Engine + compose plugin, git, git-lfs, python venv, then
# initialises Git, Git LFS and DVC (with a LOCAL remote - no cloud).
set -euo pipefail
cd "$(dirname "$0")/.."

step() { echo -e "\n\033[1;36m==> $*\033[0m"; }

step "System packages"
sudo apt-get update -y
sudo apt-get install -y git git-lfs python3 python3-venv python3-pip make curl ca-certificates

if ! command -v docker >/dev/null 2>&1; then
  step "Docker Engine (official convenience script)"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "NOTE: log out and back in (or run 'newgrp docker') so docker works without sudo."
fi
docker compose version >/dev/null 2>&1 || sudo apt-get install -y docker-compose-plugin

step "Python virtualenv (.venv) for tests, lint and DVC on the host"
make venv

step "Git + Git LFS"
[[ -d .git ]] || git init -b main
git lfs install --local
git config core.autocrlf input

step "DVC (local remote at ~/dvc-storage)"
# shellcheck disable=SC1091
source .venv/bin/activate
[[ -d .dvc ]] || dvc init
mkdir -p "$HOME/dvc-storage"
dvc remote add -d -f --local localstore "$HOME/dvc-storage"
dvc config core.autostage true

step "Secrets"
bash scripts/make_env.sh

step "Git hooks (pre-push runs the local CI)"
bash scripts/install_git_hooks.sh

mkdir -p reports data/feedback logs models
if ! git rev-parse HEAD >/dev/null 2>&1; then
  step "Initial commit"
  git add -A
  git -c user.name="${GIT_NAME:-student}" -c user.email="${GIT_EMAIL:-student@localhost}" \
      commit -qm "Initial commit: Financial Complaint Router" --no-verify
fi

echo -e "\n\033[1;32mSetup complete.\033[0m Next:  make up   then   make train"
