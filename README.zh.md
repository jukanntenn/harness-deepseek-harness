# harness-deepseek-harness

[English](README.md) | 中文

[![CI](https://github.com/jukanntenn/harness-deepseek-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jukanntenn/harness-deepseek-harness/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

面向 Python 生态、经 [prek](https://github.com/j178/prek) 接线的可复用治理门禁：GitHub 议题/PR 策略、双语文档配对、文档门禁、PR 工作流工具。外部项目通过让 prek 指向本仓库来采纳这些门禁；本仓库自身也使用它所发布的同一批钩子。它把仓库约定变成机器执行的检查、而非依赖评审者的记忆——组织与个人账户皆可运行。

## 仓库内容

- **议题策略**（`.github/issue-management/`、`.github/workflows/issue-policy.yml`、`issue-lifecycle.yml`）：议题模板、PR 模板，以及一个校验议题正文、标题、标签、议题分类（组织账户用原生 Type、个人账户用 `type/*` 标签）、Project 状态，校验 PR 标签分类（恰好一个 `kind/*`、至少一个 `area/*`）、同仓议题引用与 Priority 同步，并把事件驱动的生命周期流转（`review_requested` → In review，`changes_requested` → In progress）投影到被解决议题 Project 状态上的 Python 引擎。
- **双语文档配对**（`hdsh.pairing`）：范围内每篇文档都是英文/中文配对，外加记录 blob hash 的一致性 sidecar（`foo.i18n.yaml`），由 `hdsh-pairing-verify` 强制执行，并由 fail-closed 的 Git 合并驱动跨合并合成；`hdsh pairing brief` 为扩展翻译工作流渲染最小更新的工作集。契约见 [docs/i18n/README.zh.md](docs/i18n/README.zh.md)。
- **文档门禁**（`hdsh.docs`）：`hdsh-docs-wrap` 强制每个散文段落占一个物理行，`hdsh-docs-links` 验证相对链接与 `#fragment` 锚点可解析，`hdsh-docs-budgets` 让常驻文档保持在 `wc -w` 词数上限内；各自语料范围来自 `.hdsh/docs.manifest.json`。
- **PR 工作流工具**：`hdsh-scope` 报告一次变更的显式已提交与 worktree 范围；`hdsh worktree install` 以拒绝覆盖的安全性安装 worktree 本地的 prek 钩子与合并驱动；`.agents/skills/` 承载 pre-push、堆叠 PR 合并、代码评审与 CI 可靠性工作流；`.agents/rfcs/` 保存拥有"为什么"的 RFC（决策记录）。

## 工具链

[uv](https://github.com/astral-sh/uv) 管理项目与锁文件；[ruff](https://github.com/astral-sh/ruff)（最严规则集）负责格式化与 lint；[basedpyright](https://github.com/DetachHead/basedpyright) 以 `all` 模式类型检查，[ty](https://github.com/astral-sh/ty) 作为次要检查器；pytest 以分支覆盖率要求 100%。放宽标准须先经一份被接受的 RFC。

## 在其他仓库中使用这些门禁

```yaml
# .pre-commit-config.yaml (or prek.toml) in the consuming project
repos:
  - repo: https://github.com/jukanntenn/harness-deepseek-harness
    rev: v0.1.0  # pin the release tag you adopt
    hooks:
      - id: hdsh-pairing-verify
      - id: hdsh-rfc-verify
      - id: hdsh-rfc-archive
      - id: hdsh-docs-wrap
      - id: hdsh-docs-links
      - id: hdsh-docs-budgets
      # hdsh-scope runs at the manual stage; pass args like [--base, origin/main]
```

配对门禁从使用方仓库的 `.hdsh/pairing.manifest.json` 读取语料范围，文档门禁从 `.hdsh/docs.manifest.json` 读取；配对契约与清单规则见 [docs/i18n/README.zh.md](docs/i18n/README.zh.md)。

## 开发

```sh
uv sync                     # create the environment
uv run prek install         # local git hooks (or: uv run hdsh worktree install for worktree-local)
uv run pytest               # tests with the 100% coverage gate
uv run ruff check .         # lint
uv run ruff format .        # format
uv run basedpyright         # type check
uv run hdsh pairing list   # bilingual pairing state
```

每个非平凡变更都要随附 `.agents/rfcs/` 中的一份 RFC，并保持文档配对一致；常驻规则见 [AGENTS.md](AGENTS.md)。

## 社区与支持

- 使用与采纳问题 → [Discussions](https://github.com/jukanntenn/harness-deepseek-harness/discussions) 问答区；有价值的讨论将被沉淀为 RFC。
- 可复现缺陷与具体功能请求 → [Issues](https://github.com/jukanntenn/harness-deepseek-harness/issues)，使用对应模板。
- 安全 → [私密漏洞报告](https://github.com/jukanntenn/harness-deepseek-harness/security/advisories/new)，绝不开公开 issue；[安全策略](docs/SECURITY.zh.md)拥有完整政策。
- 社区尽力而为的支持；无商业支持、无 SLA。

## 参与贡献

任何变更先开 issue——包括拼写修正；PR 遵循清单并需要来自不同账号的一个批准；非平凡变更随附 RFC；文档以双语配对移动。[贡献指南](docs/CONTRIBUTING.zh.md)承载细节；`good first issue` 标注的 issue 是入门点。由 jukanntenn 与贡献者尽力维护。

## 许可

[MIT](LICENSE)
