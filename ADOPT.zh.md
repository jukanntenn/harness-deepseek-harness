# 接入 harness

[English](ADOPT.md) | 中文

本文是消费方侧操作手册：带一个仓库——通常经由其 AI（人工智能）agent（智能体）——从零走到完整 harness。机械的一半是 `hdsh adopt`；本页承载判断的一半：参数、git 外状态、以及「完成」的判据。接入即采纳目录树约定：所有 README、根目录 ADOPT 文档、`docs/**`、`.agents/rfcs/**` 一并进入[双语配对语料](docs/i18n/README.zh.md)。

## 阶段 1 —— git 外清单

接入从 GitHub 上开始，先于任何文件落盘：`hdsh adopt plan` 与 `apply` 都要求 `--project-number`，而其背后的看板在这里创建。apply 看不到 GitHub 上的仓库状态；消费方的 agent 执行以下各项，由人确认结果。`hdsh adopt checklist` 以可执行命令打印完整枚举：

- 创建标签体系：`kind/*` 全集、首批 `area/*` 标签，user 账户另有 `type/*` 标签（`gh label create <name> --description <...>`）。
- 创建 Project 看板：配置的状态集，外加 `Priority` 与开始日期字段；其编号即 `--project-number`。操作者令牌需要 `project` scope（`gh auth refresh -s project`）；gh 无法编辑内置 Status 选项；一条 GraphQL `updateProjectV2Field` 调用可一次设好全部七个——`hdsh adopt checklist` 打印这两条命令。
- 组织形态：为具有 Issues 与组织 Projects 权限的 GitHub App 设置 `vars.HDSH_ISSUE_APP_CLIENT_ID` 与 `secrets.HDSH_ISSUE_APP_PRIVATE_KEY`。user 形态：设置由生命周期账户持有的 `secrets.HDSH_ISSUE_PROJECT_TOKEN`（classic PAT，`project` scope）。
- 合并前要求一票批准。

## 阶段 2 —— 安装

先主机安装 hdsh（PyPI 发布前用 `uv tool install "harness-deepseek-harness @ git+<url>@<ref>"`），用 `hdsh adopt preflight` 确认工具链（git、已认证的 gh、裸 `hdsh --version`、以及 `rg --version`——各 skill 以 ripgrep 为前提），带上阶段 1 的编号审阅 `hdsh adopt plan` 后再 `hdsh adopt apply`。两者都显性失败——每个阻塞一条诊断：

只有 Project 编号与标题需要手输；其余缺省时自动推导（ref 取上游最新 tag、账户类型取 remote、actor 取 gh 身份、时区取系统——接入 RFC 日期仅首记一次，重跑复用），每个推导回显、每个旗标可覆盖、全旗标运行离线。apply 写入 prek 门禁条目与 `.gitattributes` 驱动行、两个薄策略 workflow、策略 `config.json`、issue 与 pull-request 模板、RFC 机制、全部九个 skill（五个镜像、四个槽位引导）、文档标准与 i18n 契约、actionlint 桥接文件、模板化的 `architecture.md` 与 `development.md` 配对，并在没有根 `AGENTS.md` 时写入模板化的常令文件。它记录自己安装的每一对双语配对——既存的 `architecture.md` 或 `development.md` 连同对侧模板与记录一并免写——打印发现的配对语料规模与存量语料的 wrap 重排成本，并写下 `.hdsh/adopt.manifest.json`。接入 PR 是 workflow 认得的引导时刻：合并前两个 workflow 只对它跳过并注记，其余没有可用策略 config 的运行显性失败——无论接入是引入 config 还是替换旧有配置，都无需带红合并。

## 阶段 3 —— 补全判断的一半

为整个语料配对，而不是一篇 README：任意深度的每对 README 都会被自动发现，`docs/**` 与 `.agents/rfcs/**` 按前缀加入，manifest 的 `roots` 再拉入更多子树——`hdsh pairing list` 逐一枚举；翻译每篇对侧后执行 `hdsh pairing record <anchor>`。中文优先的文档先翻转：`git mv docs/foo.md docs/foo.zh.md` 让既有内容成为中文侧，再翻译英文 `docs/foo.md`。填掉每一个 `TODO(adopt):` 占位符；`<!-- hdsh:slot ... -->` 标记内的值归消费方所有——填充它但保留标记行，下次 apply 靠它们保留已填的值。若跳过了既存的根 `AGENTS.md`，把 harness 指针并入其中。把缺失镜像侧读作删除的 skills 镜像工具（`.claude/skills/` ↔ `.agents/skills/`）运行前必须先看到整棵已装 `.agents/skills/` 树复制到镜像侧，否则它会删掉全部九个 skill。`hdsh adopt verify` 报告剩余占位符与漂移——包括一条门禁都不跑的 CI、缺失 `hdsh` 组的 `prek run --group` 过滤、仍带 `uv run hdsh` 的移植文件；完成 = verify 绿 + 各文档门禁全绿。

## 阶段 4 —— 本地工作流层

hdsh 已在阶段 2 主机安装；每个 worktree 运行一次 `hdsh worktree install` 装 prek 钩子与配对合并驱动，二者从 PATH 解析它。托管钩子带有 `hdsh` 组；CI 中每条带过滤的 `prek run` 都必须包含 `--group hdsh`，否则所有门禁静默退出运行——verify 会拒绝该缺失。不跑 prek 的 CI 自行接线——`prek run --all-files`，或钉版本安装 hdsh 后逐条运行托管门禁——verify 对零门禁的 CI 同样拒绝。apply 写入 `.github/actionlint.yaml` 桥接（按文件、按消息正则的 schema），过滤较旧 actionlint 对 `field_added`、`field_removed` 触发器的误报；该文件链接了官方文档所列活动类型，并写明移除条件。升级以更新的 ref 重跑 `hdsh adopt apply`。生成文件归上游所有：本地改动请引回上游，不要分叉。共享同一轮 prek 的消费方格式化器（prettier、shfmt 等）必须排除被安装路径——模板、`docs/i18n/**`、`.agents/**`、`.hdsh/**`——否则门禁在同轮标红其改写。

## 退役既存的本地文档标准

hdsh 是 opinionated 的：adopt 不与仓库自有的门禁协商双标准。当 wrap 检查、词数预算、配对语料或决策记录树已经存在时，在同一次接入中将其退役：把决策记录以完整三元组迁入 `.agents/rfcs/`，把词数上限并入 [.hdsh/docs.manifest.json](.hdsh/docs.manifest.json)、语料子树以 roots 并入 [.hdsh/pairing.manifest.json](.hdsh/pairing.manifest.json)，删除本地门禁脚本，并以一条 implemented RFC 记录退役。既存的 `.pre-commit-config.yaml` 会阻塞 apply，直到迁移为 `prek.toml`；把槽位标记注释当散文解析的本地 wrap 门禁会与移植 skill 冲突——退役它，而不是打补丁。此后 wrap 规则覆盖整个被接入的语料，而不只是 hdsh 安装的文件：硬换行的存量文库要一次性重排为一段一行——`hdsh adopt plan` 会预先清点这些段落，让重排作为一次预算好的机械提交落地，而不是 apply 之后的一面红墙。
