# harness-deepseek-harness 架构

[English](architecture.md) | 中文

在修改 `src/hdsh/` 下的任何内容之前先读本文。它是包的有序地图——域、统一 CLI 与新行为的去处；决策理由在链接的 RFC 中。

## 这个包是什么

hdsh 把治理门禁打包给 Python 生态：GitHub Issue/PR 策略、双语文档配对、文档语料门禁与 PR 工作流工具。外部项目通过 prek 指向 [.pre-commit-hooks.yaml](../.pre-commit-hooks.yaml) 来消费这些门禁；本仓库使用自己发布的同款钩子。域边界之下的一切都属于该域；根 [AGENTS.md](../AGENTS.md) 承载常设约定与命令清单。

## 域包与统一 CLI

`src/hdsh/` 按域组织，一个名字在三层标识同一个概念：目录、CLI 域、prek hook-id 前缀（[决策](../.agents/rfcs/implemented/architecture/2026-09-07-domain-packages-and-unified-cli.zh.md)）。

`hdsh.cli` 拥有两级 argparse 树 `hdsh <domain> <command>`：每个域包注册自己的命令叶解析器并保留其语义校验与消息，语法错误以 `ValueError` 经 `hdsh.cliargs` 浮出，处理器返回整数退出码，且契约统一——0 绿、1 违规、2 用法。`scope` 是刻意的单命令例外：它没有子命令，直接在域层注册自己的 flag。

门禁配置镜像域划分：pairing 读 `.hdsh/pairing.manifest.json`（`excluded` 数组加可选的 `generated` 数组——后者列出免于英侧切换行的生成英文源），文档门禁读 `.hdsh/docs.manifest.json`，两个解析器在加载期对不支持的字段报错退出。

## 核心包

| 包 | 拥有 | CLI 面 |
|---|---|---|
| [`pairing/`](../src/hdsh/pairing/) | 双语配对门禁、记录、合并驱动与简报工具 | `hdsh pairing verify/record/list/merge/brief` |
| [`docs/`](../src/hdsh/docs/) | 文档语料门禁：wrap、links、budgets | `hdsh docs wrap/links/budgets` |
| [`rfc/`](../src/hdsh/rfc/) | RFC 格式门禁与冻结档案门禁 | `hdsh rfc verify/archive/seal` |
| [`policy/`](../src/hdsh/policy/) | GitHub Issue/PR 策略引擎：规则、客户端、生命周期命令 | `hdsh policy` |
| [`worktree/`](../src/hdsh/worktree/) | worktree 本地 prek 钩子与合并驱动安装 | `hdsh worktree install` |
| [`scope.py`](../src/hdsh/scope.py) | 一次变更的已提交加 worktree 范围报告 | `hdsh scope` |

## Pairing

pairing 域最大，因为它拥有的是一个持久契约而不仅是检查：`foo.md`、`foo.zh.md` 与 `foo.i18n.yaml` 一致性记录整体合并，记录的 blob hash 兼作钉在内容寻址快照 ref 下的恢复指针。门禁检查配对完整性、记录的 hash、语言切换行（含 manifest `generated` 豁免）、链接 locale、逐字节一致的生成区块与结构签名；`hdsh pairing merge` 跨 Git 合并以 fail-closed 方式组合记录；`hdsh pairing brief` 为扩展翻译工作流渲染最小更新的工作集。契约见 [docs/i18n/README.md](i18n/README.zh.md)，决策见其 [RFC](../.agents/rfcs/implemented/process/2026-09-07-bilingual-pairing-gate.zh.md) 与[简报 RFC](../.agents/rfcs/implemented/process/2026-09-07-briefed-minimal-translation-updates.zh.md)。

## 文档与 RFC 门禁

docs 域保持 Markdown 语料的机械整洁：每个散文段落一个物理行、可解析的相对链接与 `#fragment` 锚点、以及 `wc -w` 上限之内的常驻文档——全部经 docs manifest 配置，预算变红的应对是搬迁或压缩。rfc 域拥有决策记录格式：生命周期目录、类别目录、头部块与各生命周期的正文骨架，加上承载冻结历史的封存档案。范围规则与 manifest 归 [docs/AGENTS.md](AGENTS.md) 所有，配对契约归 [docs/i18n/README.md](i18n/README.zh.md)，RFC 机制归 [.agents/rfcs/README.md](../.agents/rfcs/README.zh.md)。

## Policy

policy 域是唯一与 GitHub API 交互的域：`policy/rules.py` 校验 Issue 正文、标题、标签、原生 Type 与 PR 标签分类；`policy/client.py` 以互不相同的凭据分离仓库读取与 Project 读取；`policy/commands.py` 从经过校验的配置文件与事件载荷驱动两个工作流入口（`pr`、`lifecycle`）。工作流粘合层在 `.github/workflows/` 并直接调用 CLI——工作流中没有内联 Python（[决策](../.agents/rfcs/implemented/process/2026-09-07-github-workflow.zh.md)）。

## Worktree 与 scope

`worktree install` 以对自己所属路径拒绝覆盖的安全性，注册 worktree 本地 prek 钩子与 `hdsh-pairing` 合并驱动；`scope` 报告一次变更显式的已提交与 worktree 范围，让推送前检查的选择有机械输入。两者存在的原因是贡献者在堆叠 worktree 中工作，而多个 checkout 共享同一仓库时，按 worktree 的配置是钩子与驱动保持正确的唯一方式。

## 新行为的去处

| 目标 | 机制 |
|---|---|
| 加一个门禁 | 在所属域包加模块、它注册的命令叶、`.pre-commit-hooks.yaml` 的 hook-id 条目，以及需要配置时的 manifest 键 |
| 加一个域 | 新包、`hdsh.cli` 的 `_COMMAND_DOMAINS` 条目，以及遵循 `hdsh-<domain>-<command>` 前缀规则的 hook id |
| 加门禁配置 | 带加载期报错的 manifest 字段；绝不是 `DEFAULT_*` 常量或测试钩子 |
| 扩展配对契约 | 同一变更里更新 [docs/i18n/README.md](i18n/README.zh.md) 与门禁；结构签名及其语法留在 `pairing/structure.py` |
| 加仓库策略规则 | 扩展 `policy/rules.py` 并以覆盖封闭标签集的测试锁定；工作流文件订阅事件，不实现策略 |
| 改 RFC 规则 | 同时更新 `.agents/rfcs/README.md` 与 `rfc/format.py`；门禁拒绝文档所列类别之外的目录 |
| 加可复用的 agent 工作流 | `.agents/skills/` 下的技能；技能承载流程，RFC 承载决策 |
| 记录某事为何如此 | `.agents/rfcs/` 中的一篇 RFC（[规则](../.agents/rfcs/README.zh.md)）；只有机械、局部的编辑豁免 |

贡献者入口——安装、日常工作流、Git 集成、CI——见 [development.md](development.zh.md)。
