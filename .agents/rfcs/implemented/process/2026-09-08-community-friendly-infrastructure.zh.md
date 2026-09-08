# RFC: 社区友好基础设施

Status: implemented

[English](2026-09-08-community-friendly-infrastructure.md) | 中文

## 问题

本仓库为其他项目提供治理门禁，自己的社区面却是空的：没有行为准则、贡献指南、安全政策或私密报告渠道、支持分流、Discussions 阵地、评审路由，也没有仓库描述与 topics。README 回答了「项目做什么」，却没有回答「哪里获得帮助」「谁在维护」，消费方接入示例也偏离了实际发布的钩子清单。一个不示范自己能帮助执行的社区标准的治理框架，损害的是它自己的立论。

## 决策

### 社区散文文件以受门禁的双语对形式住在 `docs/`

`CODE_OF_CONDUCT.md`、`CONTRIBUTING.md`、`SECURITY.md`、`SUPPORT.md` 平铺在 `docs/` 下，各自是带一致性记录的英中配对。GitHub 认可 `docs/` 位置的这四个文件，社区标准清单照常打勾；而 `docs/**` 本就在配对语料内——配对、硬换行、链接三个既有门禁零引擎改动即覆盖新文件。无散文孪生的机械文件留在 `.github/`：pull-request 模板与 `CODEOWNERS`。

### README 补全社区五问

README 保留「做什么/怎么上手」各节，补上缺失的两问：一句价值主张（把约定变成机器执行的检查，组织与个人账户皆可运行）、Community & support 一节分流到 Discussions、Issues 与私密漏洞报告、Contributing 一节点名维护者与 issue-first 规则、以及 License 一节。新增 CI 与 License 两枚徽章；消费方示例列全七个已发布钩子，并附「钉住你采纳的 release tag」注记——尚未发布任何版本，注记陈述意图而不点名具体 tag（已对照钩子清单核验）。

### Contributor Covenant 2.1，双语逐字

行为准则是 Contributor Covenant 2.1 英文原文与其官方简体中文译本，除语言切换行外一字未改；执法联系方式 jukanntenn@outlook.com。逐字标准文本不设词数预算。

### CONTRIBUTING 是入口，不是第二本规则书

贡献指南承载流程骨架——issue-first（含拼写修正）、RFC 随 PR 同行、配对一起动、最小命令集、pull-request 机制、接受范围、AI 辅助工作的「能解释每一行」声明——并链接 AGENTS.md、RFC 规则与 i18n 契约作为权威归属，而不复述它们。

### SECURITY 仅路由到私密漏洞报告

报告走 GitHub 私密漏洞报告（作为仓库设置启用）；政策写明 7 天内确认、修复时限随严重度、经已发布 Security Advisory 协调披露并经 Dependabot 传导、报告者署名。信任边界双向：issue 与 PR 内容是策略 workflow 的不可信输入，针对它的攻击在范围内；使用方仓库自身的配置文件属于其信任域。首版发布前，`main` 是唯一支持面。

### SUPPORT 按情形分流并写明反范围

分流表把使用问题导向 Discussions（欢迎英文或中文；工作语言仍为英文）、缺陷导向 issue 模板、安全导向私密报告。反范围点名上游工具（prek、uv、GitHub Actions）与使用方治理决策不在服务范围，并声明尽力而为、无 SLA。

### Pull-request 模板新增两条护栏注释

「尽早开 draft」与「未披露的漏洞绝不走公开 PR」加入既有的引用与优先级注释；issue 模板维持现状。

### Discussions 承载未成形讨论；RFC 拥有已成形决策

Discussions 以六个默认类目启用，配受控文案——Announcements（维护者发版与破坏性变更）、General、Ideas（「功能想法与方向讨论；有价值的讨论将被沉淀为 RFC，RFC 回链本讨论」）、Polls（重大决策前的民意）、Q&A（使用提问；缺陷报告去 Issues）、Show and tell（使用方展示）——外加 General 里一篇置顶的双语欢迎帖，写明三场地分工。桥规则：推动共识者把结论沉淀为 RFC，RFC 回链来源讨论；错投条目在 Issues 与 Discussions 间转换。RFC 规则本身不变——它管记录，不管场地。

### CODEOWNERS 把评审路由到评审身份

`* @gh2bda` 把每次变更路由到实际做评审与批准的账户，与[身份模型](../feature/2026-09-08-user-account-issue-policy.zh.md)一致：开发者身份（agent 绑定的账户）提交 PR，机器账号在浏览器端评审与批准，作者不能自批。登录名是部署事实，由 `CODEOWNERS` 的路由行与策略配置的 `lifecycleActor` 承载；本记录绑定角色，不绑定用户名——换一套账户体系时改这两处事实即可，决策不变。注释式未来 owner 槽位映射各领域包；信任边界注记让 `.github/workflows/` 与 `.github/issue-management/` 保持维护者持有——它们铸造 CI 凭据、校验受信策略。code-owner 必审保持关闭；一个批准门是一种机制。

### git 外资产以本记录为防漂移清单

仓库描述（"Reusable governance gates for the Python ecosystem: GitHub issue/PR policy, bilingual documentation pairing, and pull-request workflow tooling, wired through prek"）、十一个 topics——`python`、`pre-commit`、`pre-commit-hooks`、`github-actions`、`code-quality`、`documentation`、`i18n`、`governance`、`rfc`、`ai-agents`、`developer-tools`——以及 Discussions 类目文案、欢迎帖、私密报告开关，都只以仓库状态存在；本记录是它们的 git 内真源。社交预览图待品牌资产就绪后再补。

## 验证

`uv run hdsh pairing verify` 覆盖四个新配对与重记录的 README 配对；`uv run hdsh rfc verify` 覆盖本记录；`uv run hdsh docs wrap|links|budgets` 以新上限（README 600/600、CONTRIBUTING 550/550、SECURITY 350/350、SUPPORT 250/250）覆盖语料。消费方示例的钩子清单已对照 `.pre-commit-hooks.yaml` 核验。落地后核验了 git 外状态：社区标准清单全绿、线上 topics 与本记录一致、六个类目与上述文案一致、欢迎帖已置顶、Security 页可见私密报告入口。`hdsh-rfc-archive` 已确认在没有 `.agents/rfcs/archived/` 内容的树上通过，使「列全七钩子」的示例对使用方诚实。

## 备选方案

**社区文件放仓库根目录或 `.github/`。** 在配对语料之外，其中文孪生将逃过所有门禁——恰是门禁要抓的腐烂；`docs/` 位置被 GitHub 认可且已被门禁覆盖。

**社区面报告用 YAML issue forms。** 引擎的正文契约（折叠区外可见正文 ≤50 单位）作用于每个 issue，而 form 生成的正文把用户输入放在折叠区外；事后审计才是强制力，故 markdown 模板保留。

**实现前先提独立 RFC PR。** 设计已在动手前与维护者逐主题定案；same-PR 规则与 implemented/proposed 判据（「已做出的决策以 implemented 开始」）使单 PR 正确。两段式仍适用于真正未讨论的新设计。

**中文 Covenant 附「以英文为准」注记。** 配对契约授予两种语言同等权威；标准译本惯例中的「以原文为准」被舍弃以维持该契约。

**CODEOWNERS 写 `* @jukanntenn`。** 把评审请求路由到不能自批的作者；标杆规则适配本身份极性后应指向实际评审的账户。

**流程向 topics（ci、automation、lint）。** dcs 先例——每个 topic 都应是使用方会搜索或浏览的词；流程内部词带不来受众。

**分支保护开启 code-owner 必审。** 与既有的单批准门重复；一套机制，不开两套。

## 后果

- 社区面完全双语且受门禁约束：又多出四个必须永远一起移动的配对，其词数上限迫使未来的扩充走「搬移」而非「堆积」。
- git 外资产可能悄然偏离本记录——类目文案、欢迎帖、topics 与报告开关没有机械校验；本记录是周期审计的比对源，与标杆记录过的失效模式相同。
- issue 模板按明确搁置保持极简：在折叠区内增强字段随时可行且不碰策略；待真实录入摩擦出现时再重议「什么都不做」的决定。
- README 消费示例以意图而非名称引用尚不存在的首个 release tag；日后发布 v0.1.0 时一词改动即可把注记变成具体 tag。
- Discussions 给唯一维护者新增一块治理面：Q&A 与 Ideas 的文案刻意把缺陷报告与可跟踪工作推回 Issues，让模板与策略引擎承担负荷。
