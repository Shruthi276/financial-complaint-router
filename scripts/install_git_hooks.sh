#!/usr/bin/env bash
# Installs a pre-push hook that runs the local CI (lint + tests + dvc status).
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -d .git ]] || { echo "Not a git repository - skipping hooks."; exit 0; }
cat > .git/hooks/pre-push <<'EOF'
#!/usr/bin/env bash
# Auto-installed by scripts/install_git_hooks.sh - skip with: git push --no-verify
bash scripts/ci.sh --quick
EOF
chmod +x .git/hooks/pre-push
echo "Installed .git/hooks/pre-push"
