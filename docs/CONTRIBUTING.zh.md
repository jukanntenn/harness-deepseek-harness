# 贡献指南

[English](CONTRIBUTING.md) | 中文

欢迎贡献——issue、代码、文档与翻译都是贡献。本页是入口：只承载流程骨架，链接权威规则而不复述。参与即表示你同意遵守[行为准则](CODE_OF_CONDUCT.zh.md)。

## 基本规则

- 任何变更先开 issue——包括拼写修正。PR（Pull Request）正文以 `Fixes #NN`（解决并自动关闭）或 `Related to #NN`（仅关联）引用它；PR 进入评审后，Issue policy CI 检查会强制校验引用与标签分类。
- 非平凡变更在同一 PR 内随附 RFC（决策记录）；纯机械性的局部编辑豁免（[规则](../.agents/rfcs/README.zh.md)）。
- 双语配对（bilingual pair）一起动：改任意一侧，同一 PR 更新对侧文件并重新记录配对（[契约](i18n/README.zh.md)）。

## 开发环境

Python ≥ 3.12 与 [uv](https://github.com/astral-sh/uv)；`uv sync` 创建环境，`uv run hdsh worktree install` 安装 worktree 本地钩子。最小命令集：

```sh
uv run pytest               # tests with the 100% coverage gate
uv run ruff check .         # lint
uv run basedpyright         # type check
uv run hdsh pairing verify  # bilingual pairing gate
```

完整命令清单与证据选择规则见 [AGENTS.md](../AGENTS.md)：为你的 diff 选最窄的检查集合，穷举矩阵交给 CI。

## Pull request

需要时可尽早开 draft，检查通过后标记 ready。正文引用 issue 并带上 pull-request 模板的清单；标签为变更分类——恰好一个 `kind/*`、至少一个 `area/*`。评审需要一个来自不同账号的批准，合并使用 merge commit，依赖链以原生 stack 落地（[合并技能](../.agents/skills/merging-stacked-prs/SKILL.md)）。提交标题遵循 Conventional Commits 风格——这是约定，不是门禁。

## 接受范围

无需预先讨论即可提交：门禁改进、文档与翻译更新、带测试的新校验、仓库卫生。以下先讨论——开 issue 或发 [Discussion](https://github.com/jukanntenn/harness-deepseek-harness/discussions)——再动手：改标签分类学、放宽任何严格默认值、重塑门禁强制执行的契约；放宽必须先有一份被接受的 RFC。

## AI 辅助贡献

你必须能解释自己提交的每一行——包括 AI 助手生成的代码。向本仓库贡献的 agent 遵循 [AGENTS.md](../AGENTS.md)。

## 求助

去哪提问、什么样的报告算可操作、什么不在服务范围，见[支持指南](SUPPORT.zh.md)。
