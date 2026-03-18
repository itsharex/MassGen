# 🚀 Release Highlights — v0.1.65 (2026-03-18)

### 🔧 [MassGen Refinery Plugin](https://github.com/massgen/massgen-refinery)
Standalone MCP servers that bring MassGen's quality gates and multi-round workflows to Claude Code — no full orchestrator needed. Single-agent refinement is fully working; multi-agent coordination is experimental.

### ✅ [Quality Server](https://github.com/massgen/MassGen/blob/main/massgen/mcp_tools/standalone/quality_server.py) (`massgen_quality_tools`)
- **Session-based evaluation**: Timestamped quality sessions with criteria storage in `.massgen-quality/`
- **Checklist scoring**: Evaluate answers against stored criteria with configurable thresholds
- **Improvement proposals**: Coverage validation that identifies unmet criteria and suggests gaps for refinement

### 📋 [Workflow Server](https://github.com/massgen/MassGen/blob/main/massgen/mcp_tools/standalone/workflow_server.py) (`massgen_workflow_tools`)
- **Multi-round answers**: Submit answers with automatic deliverable snapshots into round directories for traceable iteration
- **Vote support**: Stateless passthrough for agent consensus mechanisms

### 🖼️ [Media Server](https://github.com/massgen/MassGen/blob/main/massgen/mcp_tools/standalone/media_server.py) (`massgen_media_tools`)
- **Generate media**: Text-to-image/video/audio with optional input media, auto-detects available backends (Google Gemini, OpenAI, Grok, ElevenLabs)
- **Read media**: Analyze media files with critical-first ordering and multi-file comparison

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.65
  # The standalone MCP servers are available for the massgen-refinery Claude Code plugin
  ```
