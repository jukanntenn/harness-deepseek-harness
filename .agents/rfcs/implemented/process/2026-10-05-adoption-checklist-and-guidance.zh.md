# RFC: 机器可读的 Phase 1 清单与三处指引缝隙

Status: implemented

[English](2026-10-05-adoption-checklist-and-guidance.md) | 中文

## 问题

第四个接入方在入口处撞上三处指引缝隙。其一，Phase 1 的枚举——标签体系、七个看板状态、`Priority` 与开始日期字段——只以源码常量存在（`rules.py`、`corpus.py`）；`hdsh adopt plan` 要求 `--project-number`，建看板之前的操作者除了读源码无物可读。其二，preflight 报「gh authenticated」，而建看板实际需要 `project` scope——这个操作者层面的事实被[向导 RFC](../feature/2026-10-01-guided-adoption-wizard.zh.md) 留给了手册；操作者到建看板那一步才发现缺口。其三，[翻译规则](../../../../docs/i18n/translation-rules.zh.md)说纯页内 fragment 保持不变，却没有告诉译者 GitHub 生成 CJK 标题 slug 时保留原字符——不变的 fragment 因此只在中文侧紧邻显式 `<a id>` 锚点时才能解析，这个 pattern 语料自身已在用（RFC 索引、i18n 契约 README），规则手册却从未写明；配对门禁的 fragment 全等比较与链接门禁的可解析要求于是读起来互相矛盾，正如[语料门禁 RFC](../process/2026-09-07-document-corpus-gates.zh.md) 所记录。gh 此后已内置原生 `gh project` 命令，手册的「消费方的 agent 执行这些」如今可以字面成立——内置 Status 字段的选项除外。

## 决策

- `hdsh adopt checklist` 以可直接复制执行的命令打印 Phase 1 枚举，全部派生自单一来源：policy rules 中的 `LABEL_DESCRIPTIONS`——经测试钉死为恰好的封闭 `kind/*`、`type/*` 与优先级集合——七个标准状态、`Priority` 单选选项、`field-create` 命令。它点名诚实的边界：gh 无法编辑内置 Status 字段的选项，七个状态在看板 UI 里设置；它也点名 `gh auth refresh -s project` 的补救。
- preflight 解析成功的 `gh auth status` 所披露的 `Token scopes:` 行，没有任何一行提到 `project` 时发出提示——不是阻塞——未披露 scopes（无法识别的输出格式）保持沉默而不是出错。提示与失败分开，因为组织部署的 workflow 由操作者令牌从不携带的 App 凭据驱动。
- 翻译规则现在写明该 pattern：两侧标题旁放置相同的 `<a id>`，链接原样指向它——两个门禁本就接受的调和方式，没有任何门禁被削弱。
- 接入手册把 Phase 1 指向 checklist，写明 scope 补救与 Status-UI 边界，并记录[引导 RFC](../bug-fix/2026-10-05-first-adoption-policy-bootstrap.zh.md) 决定的接入 PR 引导行为。

## 验证

checklist 输出经测试对常量钉死——每条 label 命令及其描述、全部七个状态、两个 field-create 形态、UI 边界与 scope 补救——分类学测试证明 `LABEL_DESCRIPTIONS` 恰好覆盖封闭标签集合。scope 提示经注入 transport（无 project、有 project、未披露）与解析器直接钉死。翻译规则与接入手册配对在配对门禁下重录绿色，改动语料通过 wrap、links 与 budget 门禁。

## 考虑过的替代方案

**只在接入手册里列出枚举。** 否决：封闭集合的第二份手工副本会偏离引擎执行的常量；命令从单一来源派生，手册指向它。

**把缺失的 scope 变成 preflight 阻塞项。** 否决：组织部署从不需要操作者令牌携带 `project`；阻塞 preflight 会为了让一个形态特定的便利提示失败掉正确的部署。

**放宽配对门禁以接受按 locale 生成 slug 的 fragment。** 否决：结构签名比较全等 fragment，因为分裂的锚点恰是它存在要去抓的分歧；显式锚点在不削弱任何门禁的前提下调和了两者。

## 后果

换来的是：Phase 1 的操作者——人或 agent——跑一条命令代替读源码，在建看板步骤之前而不是之上得知 scope 要求，译者拿到了带语料实例背书的正式 fragment pattern。

付出的是：checklist 是又一个需要与常量保持对齐的面（由测试把持），scope 提示在「仅限已披露行」的规则下读取 gh 的输出格式，而 Status 选项仍是命令只能点名、无法代劳的手工 UI 步骤。
