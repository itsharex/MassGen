# 🚀 Release Highlights — v0.1.70 (2026-03-30)

### 📋 [Evaluation Criteria Redesign](https://docs.massgen.ai/en/latest/user_guide/concepts.html)
- **Three-tier categorization**: `primary` (ONE — where the model needs most push), `standard` (must-pass), `stretch` (nice-to-have) with anti-pattern definitions per criterion
- **Aspiration statements**: Set the quality bar with a single sentence describing the ideal outcome
- **Improved criteria generation**: Criteria generation now produces opinionated, task-specific criteria

### 🔄 [Checklist-Gated Evaluation Workflow](https://docs.massgen.ai/en/latest/user_guide/concepts.html)
- **Iterative submission cycles** ([#1035](https://github.com/massgen/MassGen/pull/1035)): Agents submit, get scored against the checklist, receive improvement proposals, and resubmit before final voting
- **Scoring and gap analysis**: Drive meaningful iteration with concrete feedback

### ✨ Plus
- **Fast iteration mode** ([#1035](https://github.com/massgen/MassGen/pull/1035)): Streamlined multi-round submission phases via `fast_iteration.yaml`
- **WebUI review modal** ([#1035](https://github.com/massgen/MassGen/pull/1035)): Approve and comment on outputs directly in the browser when working in git
- **Background trace analysis** ([#1035](https://github.com/massgen/MassGen/pull/1035)): Execution trace analyzer starts automatically from round 2
- **Workspace cleanup** ([#1035](https://github.com/massgen/MassGen/pull/1035)): Enhanced isolation between rounds

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.70
  # Try the redesigned evaluation criteria
  uv run massgen --web
  ```
