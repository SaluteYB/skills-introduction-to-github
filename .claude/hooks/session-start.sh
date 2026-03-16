#!/bin/bash
set -euo pipefail

# Only run in remote (Claude Code on the web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Clone videocut-skills to ~/.claude/skills/videocut (idempotent)
SKILLS_DIR="$HOME/.claude/skills/videocut"

if [ ! -d "$SKILLS_DIR" ]; then
  echo "Installing videocut skills..."
  git clone https://github.com/Ceeon/videocut-skills.git "$SKILLS_DIR"
  echo "videocut skills installed."
else
  echo "videocut skills already installed, skipping."
fi
