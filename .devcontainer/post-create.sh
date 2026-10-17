#!/usr/bin/env bash
# Installs the toolchain from mise.toml and the project dependencies.
set -euo pipefail

curl -fsSL https://mise.run | sh
export PATH="$HOME/.local/bin:$HOME/.local/share/mise/shims:$PATH"
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc

mise trust --yes mise.toml
mise install
just setup
