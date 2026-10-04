# 接入 harness

[English](ADOPT.md) | 中文

本文是消费方侧操作手册：带一个仓库——通常经由其 AI（人工智能）agent（智能体）——从零走到完整 harness。机械的一半是 `hdsh adopt`；本页承载判断的一半：参数、git 外状态、以及「完成」的判据。接入即采纳目录树约定：所有 README、根目录 ADOPT 文档、`docs/**`、`.agents/rfcs/**` 一并进入[双语配对语料](docs/i18n/README.zh.md)。

## 阶段 1 —— 安装

先主机安装 hdsh（PyPI 发布前用 `uv tool install "harness-deepseek-harness @ git+<url>@<ref>"`），用 `hdsh adopt preflight` 确认工具链（git、已认证的 gh、裸 `hdsh --version`、以及 `rg --version`——各 skill 以 ripgrep 为前提），审阅 `hdsh adopt plan` 后再 `hdsh adopt apply`。两者都显性失败——每个阻塞一条诊断：

只有 Project 编号与标题需要手输；其余缺省时自动推导（ref 取上游最新 tag、账户类型取 remote、actor 取 gh 身份、时区取系统——时区同时决定接入 RFC 的日期），每个推导回显、每个旗标可覆盖、全旗标运行离线。apply 写入 prek 门禁条目与 `.gitattributes` 驱动行、两个薄策略 workflow、策略 `config.json`、issue 与 pull-request 模板、RFC 机制、全部九个 skill（五个镜像、四个槽位引导）、文档标准与 i18n 契约、actionlint 桥接文件、模板化的 `architecture.md` 与 `development.md` 配对，并在没有根 `AGENTS.md` 时写入模板化的常令文件。它会记录每一对已安装的双语配对，打印发现的配对语料规模，并写下 `.hdsh/adopt.manifest.json`。

## 阶段 2 —— git 外清单

apply 看不到 GitHub 上的仓库状态；消费方的 agent 执行以下各项，由人确认结果：

- 创建标签体系：`kind/*` 全集、首批 `area/*` 标签，user 账户另有 `type/*` 标签（`gh label create <name> --description <...>`）。
- 创建 Project 看板：配置的状态集，外加 `Priority` 与开始日期字段；其编号即 `--project-number`。
- 组织形态：为具有 Issues 与组织 Projects 权限的 GitHub App 设置 `vars.HDSH_ISSUE_APP_CLIENT_ID` 与 `secrets.HDSH_ISSUE_APP_PRIVATE_KEY`。user 形态：设置由生命周期账户持有的 `secrets.HDSH_ISSUE_PROJECT_TOKEN`（classic PAT，`project` scope）。
- 合并前要求一票批准。

## 阶段 3 —— 补全判断的一半

为整个语料配对，而不是一篇 README：任意深度的每对 README 都会被自动发现，`docs/**` 与 `.agents/rfcs/**` 按前缀加入，manifest 的 `roots` 再拉入更多子树——`hdsh pairing list` 逐一枚举；翻译每篇对侧后执行 `hdsh pairing record <anchor>`。填掉每一个 `TODO(adopt):` 占位符；`<!-- hdsh:slot ... -->` 标记内的值归消费方所有——填充它但保留标记行，下次 apply 靠它们保留已填的值。若跳过了既存的根 `AGENTS.md`，把 harness 指针并入其中。`hdsh adopt verify` 报告剩余占位符与漂移——包括 CI 中缺失 `hdsh` 组的 `prek run --group` 过滤与仍带 `uv run hdsh` 的移植文件；完成 = verify 绿 + 各文档门禁全绿。

## 阶段 4 —— 本地工作流层

hdsh 已在阶段 1 主机安装；每个 worktree 运行一次 `hdsh worktree install` 装 prek 钩子与配对合并驱动，二者从 PATH 解析它。托管钩子带有 `hdsh` 组；CI 中每条带过滤的 `prek run` 都必须包含 `--group hdsh`，否则所有门禁静默退出运行——verify 会拒绝该缺失。apply 写入 `.github/actionlint.yaml` 桥接（按文件、按消息正则的 schema），过滤较旧 actionlint 对 `field_added`、`field_removed` 触发器的误报；该文件链接了官方文档所列活动类型，并写明移除条件。升级以更新的 ref 重跑 `hdsh adopt apply`。生成文件归上游所有：本地改动请引回上游，不要分叉。

## 退役既存的本地文档标准

hdsh 是 opinionated 的：adopt 不与仓库自有的门禁协商双标准。当 wrap 检查、词数预算、配对语料或决策记录树已经存在时，在同一次接入中将其退役：把决策记录以完整三元组迁入 `.agents/rfcs/`，把词数上限并入 [.hdsh/docs.manifest.json](.hdsh/docs.manifest.json)、语料子树以 roots 并入 [.hdsh/pairing.manifest.json](.hdsh/pairing.manifest.json)，删除本地门禁脚本，并以一条 implemented RFC 记录退役。既存的 `.pre-commit-config.yaml` 会阻塞 apply，直到迁移为 `prek.toml`；把槽位标记注释当散文解析的本地 wrap 门禁会与移植 skill 冲突——退役它，而不是打补丁。
