# MassGen v0.1.71 Roadmap

**Target Release:** April 2, 2026

## Overview

Version 0.1.71 focuses on running MassGen as a cloud job on Modal.

---

## Feature: Cloud Modal MVP

**Issue:** [#982](https://github.com/massgen/MassGen/issues/982)
**Owner:** @ncrispino

### Goals

- **Cloud Execution**: Run MassGen jobs in the cloud via `--cloud` option on Modal
- Progress streams to terminal, results saved locally under `.massgen/cloud_jobs/`

### Success Criteria

- [ ] Cloud job execution functional on Modal
- [ ] Progress streaming and artifact extraction working

---

## Related Tracks

- **v0.1.70**: Evaluation Criteria Redesign — three-tier categorization, checklist-gated workflow, fast iteration mode ([#1035](https://github.com/massgen/MassGen/pull/1035))
- **v0.1.72**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
