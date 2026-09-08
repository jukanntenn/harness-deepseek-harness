# RFC: CI 门禁 job 先供给锁定环境再运行工具

Status: implemented

[English](2026-09-08-ci-jobs-provision-the-locked-environment.md) | 中文

## 问题

每个基于 uv 的 CI job 都在全新 runner 上直接以 `uv run --no-sync <tool>` 调用门禁，而那里从来没有人创建过项目环境。uv 生成了一个空的 `.venv`，`ruff`、`basedpyright`、`ty`、`hdsh` 的 spawn 以 `Failed to spawn: ... No such file or directory` 失败，仓库第一次 push 到 `main` 时五个 job 挂了三个（run 34213766320）。coverage job 之所以通过，只是因为 `uv run pytest` 会隐式自动 sync；hook manifest job 通过则是因为它根本不碰 uv。`--no-sync` 模式借鉴自本地 prek 钩子——那里 worktree 的 uv 管理环境是开发的既成前提；CI runner 没有这个前提，这个 flag 默默假设了一个无人构建过的环境。

## 决策

每个基于 uv 的 CI job 现在在自己的门禁步骤之前运行一个显式的 `uv sync` 步骤——锁定执行，因为 `UV_LOCKED=1` 是整个 workflow 的环境变量——所有工具调用保持 `--no-sync`，包括 coverage job 的 pytest，它此前依赖 uv 的隐式自动 sync。四个 job 共享同一形态：checkout、安装 uv、sync 锁定环境、运行门禁。

## 验证

`main` 上的第一次 CI run 是失败证据：lint、typecheck、文档门禁三个 job 死于 `Failed to spawn`，而 coverage job 的隐式 sync 证明了锁定环境可以在 runner 上干净安装。携带本变更的 push 在 `main` 上运行全部五个 job，其绿色结果即验收证据。

## 备选方案

**去掉 `--no-sync`，依赖 `uv run` 自动 sync。** 隐式默认正是显式优于隐式的边界规则所禁止的：供给动作会藏进每一次 run 调用，而不是作为 job 的解决步骤出现一次。统一的 sync 步骤还兼作响亮的锁检查——`pyproject.toml` 与 `uv.lock` 不匹配会在 job 顶部失败。

**用 composite action 封装 checkout、uv 与 sync。** 用四行可见的重复换取一层间接且无任何行为变化；重复步骤让每个 job 保持清晰与平行。

**按 lockfile 为键缓存 `.venv`。** 供给将依赖缓存恢复的正确性，陈旧键会让门禁对着一个与 lock 不再匹配的环境运行。uv 的下载缓存已让全新 sync 足够快；coverage job 含 sync 的完整运行只用 37 秒。

## 影响

- CI 执行与本地 prek 钩子逐字相同的门禁命令串，环境则严格按 `uv.lock` 供给；本地与 CI 的环境漂移无法再躲在隐式 sync 后面。
- `pyproject.toml` 与 `uv.lock` 不匹配会在每个受影响 job 顶部的 sync 步骤失败，而不是在门禁深处冒出令人困惑的「可执行文件不存在」。
- 每个 job 多付一个供给步骤；uv 下载缓存把成本压在秒级，coverage job 已经证明了这一点。
