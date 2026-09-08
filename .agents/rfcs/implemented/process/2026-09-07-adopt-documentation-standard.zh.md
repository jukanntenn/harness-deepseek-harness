# RFC: 引入文档标准

Status: implemented

[English](2026-09-07-adopt-documentation-standard.md) | 中文

## Problem

仓库已发布配对、换行、链接、预算与 RFC 格式门禁，但在其上没有任何文档标准：没有分层 taxonomy、没有教程／参考二分纪律、没有 slop 清单、没有包的有序地图，也没有根命令清单之外的贡献者入口。悬而未决的是范围：标准必须写明什么属于其中、什么留在范围之外。

## Decision

标准以本语料为范围落地：

- [docs/architecture.md](../../../../docs/architecture.zh.md) 入册为有序地图：域、统一 CLI、逐域小节与「新行为的去处」表，理由链接 RFC 而非复述。
- [docs/development.md](../../../../docs/development.zh.md) 入册为贡献者安装教程与参考：前置条件、首次安装、Git 集成（含合并驱动失败契约，链到配对契约的 `#the-pairing-contract` 锚点）、prek 钩子边界与 CI 概述。
- [docs/AGENTS.md](../../../../docs/AGENTS.md) 增补带「一事一家」各行与「不属于此处」列的分层 taxonomy、含读者分级排序与撰写顺序的教程／参考分类法、slop 清单、三步预算政策（搬迁、压缩、上调）加 5% 余量，以及直陈其事的行文规则；其词数上限由 docs manifest 持有。
- `.agents/skills/documenting` 承载布局与审计工作流：执行序列、执行式事实核查程序、voice rules、质量判据、语料审计与预算政策。
- `.agents/skills/editing-prose` 承载编辑标准：完整命题保持、按位置的必要覆盖与边界决策协议。

范围之外：新的文档层、生成式目录与站点投影；不为其中任何一项设门禁。

## Alternatives considered

**采纳最大化的标准。** 指向本仓库不发布机制的交叉引用会悬空，死链会让 docs-links 门禁第一次运行就变红。

**停留在每门禁的最小规则。** 语料已经需要布局决策（架构对开发对实操手册）并且存在 slop 失败模式；没有成文标准，这些决策每个 PR 都要重新争论，也没有任何东西审计它们。

**只引入 taxonomy，不引入技能。** taxonomy 陈述规则但不陈述应用规则的程序；审计与事实核查工作流才是 agent 真正加载的部分，而且它们是纯指导。

## Consequences

- 新常驻文档加入配对语料与预算 manifest；`docs/AGENTS.md` 的 taxonomy 是布局权威，documenting 据此审计。
- i18n README 的 `#the-pairing-contract` 锚点是合并驱动契约的入站链接目标，development.md 引用其确切接受的文件与状态。
- 两个技能是英文单边的指令文件——豁免配对、处于 wrap/links 语料之内——并且只引用本仓库发布的机制。
- 扩展标准意味着在同一变更中更新本 RFC 的范围清单，而不是重新推导什么属于其中。
