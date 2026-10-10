# RFC: 修复第二份接入报告——checklist mutation 的 schema 脱节、重绑死锁、缓存导致的红跳过

Status: implemented

[English](2026-10-10-adoption-report-follow-ups.md) | 中文

## 问题

同一接入方的后续报告带来三个缺陷。其一，阶段 1 checklist 的看板配置 mutation 已与 GitHub 的 GraphQL schema 脱节：`updateProjectV2FieldInput` 不再接受 `projectId`，且每个单选 option 现在必填固定枚举中的 color（八个取值，没有 BROWN）与 description——照抄打印的命令会以五种方式失败，接入方手工改写 mutation 才配好 Status 选项。其二，看板迁移陷入死锁：verify 的锚点检查要求 `config.json` 与 adopt manifest 一致，提交钩子运行 adopt-verify，apply 拒绝脏工作树，而与绑定 `config.json` 矛盾的 `--project-number` 旗标是阻塞项——先改 config 无法提交，先传旗标无法 apply；接入方靠同时手改两个文件解开。锚点诊断许诺的解法「以新编号重跑 hdsh adopt apply 以重绑」实际是一条无法执行的命令。其三，接入 PR 上两个策略 workflow 的跳过路径仍以失败收场：`astral-sh/setup-uv@v9` 的缓存 post 步骤因缓存目录不存在而报 error，文档承诺的「skip with a notice」呈现为该 PR 仅有的两个红检查。

## 决策

- checklist mutation 对齐 GitHub 公开的 schema 文档：input 只带 `fieldId`，七个状态 option 各自带 name、GRAY/PURPLE/BLUE/YELLOW/ORANGE/GREEN/RED 之一、以及 description。checklist 该行同时写明：在条目带有 Status 值之前运行——不带 option id 替换整个选项集会清掉既有取值。
- `hdsh adopt apply --rebind`（`plan` 同样识别）是显式的看板迁移路径：传入的 `--project-number` 与 `--project-title` 覆盖绑定 `config.json` 而不是与之矛盾，其余参数仍从该文件解析，且由本次运行亲自重渲染 `config.json`——apply 唯一会改写的 consumer-config 目标——新锚点与新绑定作为同一个可提交状态一并落地。非看板字段的矛盾仍然阻塞，脏工作树拒绝保持不变：重绑自己写这个文件，无需任何手改。verify 的锚点诊断点名该命令，并提示先回退手改。
- 两个 composite action 向 setup-uv 传 `enable-cache: false`：引擎安装只是钉版本 ref 的一个 wheel，缓存毫无收益，而其 post 步骤在缓存未命中时恰恰把跳过运行变红。

## 验证

checklist 测试钉住打印的 mutation——input 仅 fieldId、逐 option 的 color 与 description、无 `projectId` 变量或参数、无 BROWN。重绑测试证明完整回路：config 以新编号与标题重渲染而其余取值保持其 `config.json` 解析、manifest 锚点跟随、verify 不再报锚点漂移，且重绑不豁免非看板矛盾。mutation 形态对照 GitHub 公开的 GraphQL schema 校验，引擎自身的 mutation（`addProjectV2ItemById`、`updateProjectV2ItemFieldValue`）确认未变。全套测试、lint 与类型门禁重跑为绿。

## 考虑过的替代方案

**在 apply 中容忍一种脏文件，而不是重渲染 config。** 否决：为一条流程削弱「接入绝不与未提交工作混合」的全局不变量，且仍要消费方手工拼装中间状态；重绑直接渲染终态。

**让 verify 接受「config 领先 manifest 一步」作为可提交的中间态。** 否决：恰在错板事故最容易落地的窗口暂停了锚点不变量；不变量应持续显性失败，直到一条显式命令重建它。

**保留 `projectId`，只补缺失的 option 字段。** 否决：input 根本不再接受该参数，半修仍然失败。

**保留 setup-uv 的缓存默认。** 否决：钉版本 ref 每次一个 wheel，缓存无所收益，而 post 步骤的失败模式恰是引导 PR 上的红跳过。

## 后果

换来的是：阶段 1 checklist 重新可以照抄；看板迁移是一条显式命令、无需手改；接入 PR 的跳过路径呈现为跳过。代价是：重绑刻意替换 `config.json`（格式归一为 adopt 的渲染，对该文件的同时手改需重新检查），且 option 颜色是固定常量而非操作者选择——该配色是 harness 看板形态的一部分。
