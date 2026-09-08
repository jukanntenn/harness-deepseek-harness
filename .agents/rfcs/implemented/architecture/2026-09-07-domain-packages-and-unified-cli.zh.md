# RFC: 域包与统一的 hdsh CLI

Status: implemented

[English](2026-09-07-domain-packages-and-unified-cli.md) | 中文

## Problem

六个领域的门禁包需要每个概念在目录、CLI 域与 hook id 三层只用一个名字。平铺的逐门禁脚本与混杂的命名风格让公共面无从辨认，测试不按域镜像源码则会为补齐覆盖率而非描述行为而膨胀，而每个新门禁都在放大这种歧义。

## Decision

`src/hdsh/` 按领域组织，且一个概念在三层只用一个名字：目录、CLI 域、prek hook id 前缀。

- 领域包为 `pairing/`、`docs/`、`rfc/`、`scope.py`、`policy/`、`worktree/`；包内按概念拆分模块——`pairing/{manifest,corpus,records,links,structure,git,verify,merge}`、`policy/{config,rules,client,commands}`、`worktree/{git,ownership,config,install}`、`docs/{config,corpus,markdown,wrap,links,budgets}`。
- 只保留一个控制台脚本——`hdsh`（`hdsh.cli:main`，另有 `python -m hdsh`）；`cli.py` 持有两级 argparse 子命令树 `hdsh <domain> <command>`，每一层都有渐进披露的 `--help`，各域包注册自己的命令叶子解析器并保留各自的语义校验与报错（例如 pairing 的"显式批量重录"规则），语法错误以 `ValueError`、已处理的 help 以信号浮出（经 `hdsh.cliargs`），处理器返回整数退出码，`SystemExit` 只出现在进程入口与 git 边界助手。
- Hook id 遵循同一规则：`hdsh-pairing-verify`、`hdsh-rfc-verify`、`hdsh-scope`（manual 阶段）、`hdsh-docs-wrap`、`hdsh-docs-links`、`hdsh-docs-budgets`；manifest entry 直接调用子命令（`entry: hdsh pairing verify`），保持与上游 pre-commit 兼容。
- 门禁配置文件同样镜像领域——`.hdsh/pairing.manifest.json` 与 `.hdsh/docs.manifest.json`——合并驱动为 `merge.hdsh-pairing`，由 `scripts/pairing-merge-driver.sh` 承载；worktree 安装器负责注册两者。
- 测试按域镜像源码树并带包标记，共享助手位于 `tests/helpers.py`；`src/hdsh/py.typed` 将 wheel 标记为有类型（PEP 561）。

## Alternatives considered

**`gates/` 伞形目录。** 某物是不是 prek hook 是根 manifest 的属性而非源码属性；`policy` 与 `scope` 公开却不是自动 hook，这个拆分在第一个真实案例上就漏了水，还重复了包级词汇“gates”。

**独立的 hooks 镜像仓库（ruff-pre-commit 模式）。** 它的动机是带独立发布节奏的编译产物；这些门禁是从同一包发布的纯 Python，镜像只会增加一个版本对齐面。

**每个门禁一个控制台脚本。** 多入口让一个概念有多个名字，且每个入口各需一套用法语法；在外部消费者出现之前，单一入口加域子命令严格更简。

**把各域标志集中声明在单一共享解析器里。** 各域携带刻意的用法语法与诊断；共享的标志面要么重复校验要么削弱校验，因此语法留在各域自行注册的每命令叶子解析器中。

**手写名字表分发器加各域手写 argv 解析。** 两套解析机制会把同一契约维护两遍：缩写标志在有的命令被接受、有的被拒绝，缺值的标志被报成未知参数，用法表靠手抄复制每个命令的标志语法；单一 argparse 树让每一层都有渐进披露的 `--help`，退出码契约只有一个归属。

## Consequences

- 消费者对同一仓库写 `entry: hdsh pairing verify` 形式的 hooks；hook id、命令名、配置文件名与合并驱动键使用同一套域名，不留兼容垫片。
- 退出码契约统一——0 绿、1 违规、2 用法——合并驱动、解决器与安装器共享 `hdsh pairing …` / `hdsh worktree install` 面。
- 分支覆盖率经由逐域行为测试保持 100%；当某分支只能靠 monkeypatch 内部才能触达时，删除的是分支而非保留测试。
