# 🚀 Release Highlights — v0.1.66 (2026-03-20)

### 🔄 Step Mode
- **One agent, one step, then exit**: New `--step` CLI flag for external orchestrators to run a single agent iteration
- **Session directory**: Loads prior answers/workspaces and writes updated state back — source-agnostic (MassGen, Claude Code, shell scripts)
- **massgen-refinery integration**: Powers step-by-step execution in the [massgen-refinery Claude Code plugin](https://github.com/massgen/massgen-refinery)

### 🪟 Codex Windows Fixes
- **UTF-8 encoding**: Ensure UTF-8 when writing files in Codex backend
- **Console text sanitization**: New utility for safe text rendering in logger and TUI event pipeline

### ✅ Fixes
- **Console safety**: Refactored text sanitization into reusable `sanitize_console_text` utility

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.66
  # Run one step of a configured agent
  uv run massgen --step --config your_config.yaml --session-dir ./my_session "Your task"
  ```
