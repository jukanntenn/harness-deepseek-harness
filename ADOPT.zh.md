# 接入 harness

[English](ADOPT.md) | 中文

本文是消费方侧操作手册：带一个仓库——通常经由其 AI（人工智能）agent（智能体）——从零走到完整 harness。机械的一半是 `hdsh adopt`；本页承载判断的一半：参数、git 外状态、以及「完成」的判据。接入即采纳目录树约定：所有 README、根目录 ADOPT 文档、`docs/**`、`.agents/rfcs/**` 一并进入[双语配对语料](docs/i18n/README.zh.md)。

## 阶段 1 —— 安装

带着下述参数运行 `hdsh adopt plan`，审阅打印出的计划，再运行 `hdsh adopt apply`。两个命令都显性失败——每个阻塞一条诊断——绝不猜测。hdsh 自身从钉住的 ref 引导：

```sh
uvx --from "harness-deepseek-harness @ git+https://github.com/jukanntenn/harness-deepseek-harness@<ref>" \
  hdsh adopt plan <parameters>
```

参数为 `--hdsh-ref`（tag 或完整 SHA；钉住全部引用）、`--account-type user|organization`、`--project-number`、`--project-title`、`--lifecycle-actor`、`--time-zone`；Project 字段名有默认值。apply 写入 prek 门禁条目与 `.gitattributes` 驱动行、两个薄策略 workflow、策略 `config.json`、issue 与 pull-request 模板、RFC 机制、全部十个 skill、文档标准与 i18n 契约、模板化的 `architecture.md` 与 `development.md` 配对，并在没有根 `AGENTS.md` 时写入模板化的常令文件。它会记录每一对已安装的双语配对，并写下 `.hdsh/adopt.manifest.json`。

## 阶段 2 —— git 外清单

apply 看不到 GitHub 上的仓库状态；消费方的 agent 执行以下各项，由人确认结果：

- 创建标签体系：`kind/*` 全集、首批 `area/*` 标签，user 账户另有 `type/*` 标签（`gh label create <name> --description <...>`）。
- 创建 Project 看板：配置的状态集，外加 `Priority` 与开始日期字段；其编号即 `--project-number`。
- 组织形态：为具有 Issues 与组织 Projects 权限的 GitHub App 设置 `vars.HDSH_ISSUE_APP_CLIENT_ID` 与 `secrets.HDSH_ISSUE_APP_PRIVATE_KEY`。user 形态：设置由生命周期账户持有的 `secrets.HDSH_ISSUE_PROJECT_TOKEN`（classic PAT，`project` scope）。
- 合并前要求一票批准。

## 阶段 3 —— 补全判断的一半

为仓库自己的 README 配对（翻译对侧，然后 `hdsh pairing record README.md`），填掉每一个 `TODO(adopt):` 占位符；若跳过了既存的根 `AGENTS.md`，把 harness 指针并入其中。`hdsh adopt verify` 报告剩余占位符与对照 adopt manifest 的漂移；完成 = verify 绿 + 各文档门禁全绿。

## 阶段 4 —— 本地工作流层

把 hdsh 加入项目（PyPI 发布前用 `uv add "harness-deepseek-harness @ git+https://github.com/jukanntenn/harness-deepseek-harness@<ref>"`），再在每个 worktree 运行 `uv run hdsh worktree install` 安装 prek 钩子与配对合并驱动。升级以更新的 ref 重跑 `hdsh adopt apply`。生成文件归上游所有：本地改动请引回上游，不要分叉。
