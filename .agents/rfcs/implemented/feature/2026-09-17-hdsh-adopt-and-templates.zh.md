# RFC: hdsh adopt 与接入模板语料

Status: implemented

[English](2026-09-17-hdsh-adopt-and-templates.md) | 中文

## 问题

没有任何东西替消费方组装 harness。接入知识散落在 README 的钩子示例、配对契约、RFC（决策记录）规则与各 skill 里；消费方需要的物料——manifest（元数据清单）种子、薄策略 workflow、issue 模板、RFC 机制文件、全部十个 skill、文档标准、实操手册（Cookbook）——是本仓库的活文件，没有带版本的分发形态。手工复制对升级不友好：复制品与源漂移，每次上游改进都造成分叉。需要消费方判断的部分——`docs/architecture.md`、`docs/development.md`、根 `AGENTS.md`——没有任何受引导的形态，每个消费方各自重新发明。两个阻塞加深了这一点：策略 workflow 胶水不可分发（[现为 composite action](2026-09-17-issue-policy-composite-actions.zh.md)）、合并驱动指向仓库内相对脚本（[现为 CLI 入口](2026-09-17-pairing-merge-driver-cli-entry.zh.md)）。缺的是：一条安装机械整体的命令、judgment 剩余部分的受引导形态、一份把消费方的 AI（人工智能）agent（智能体）从零带到全门禁仓库的文档。

## 决策

### adopt 域：plan、apply、verify

`hdsh adopt` 注册三枚命令叶子。`plan` 预检并打印完整安装计划，一字节不写；`apply` 落盘；`verify` 对照 adopt manifest 比对已装目录树并清点剩余占位符。先预检后落盘保证失败的接入不留半棵树：所有检查先行，任一阻塞即整体中止，每个阻塞一条诊断——哪个文件、为何阻塞、建议的处理。检查拒绝：非 git 目录、脏 worktree、把 `*.i18n.yaml` 指向其他驱动的 `.gitattributes` 映射、歧义的 prek 配置（遗留的 `.pre-commit-config.yaml`、非法 TOML、或 adopt 管理块之外手工钉住的 harness 条目）、以及任何已存在且内容非 adopt 所写的目标文件。prek 条目是带 `BEGIN`/`END` 标记的块——整体追加或整体替换，绝不逐行合并——并在写入前重新校验结果仍是合法 TOML。

### 模板是包数据，受等价门禁约束

可迁移语料作为包数据随 adopt 域分发，与安装的 hdsh 严格同版；adopt 不从网络读取任何东西——消费方以钉住 ref 的 `uvx --from git+...` 引导 CLI 本身。本仓库的一道执行级门禁（`tests/adopt/test_templates.py`）证明每份打包镜像与其镜像的仓库活文件逐字节相等，两份拷贝无法静默漂移——镜像维护是门禁看守下的诚实成本。

### 三类迁移

原生物料是逐字镜像或参数化生成：RFC 机制文件与目录骨架、全部十个 skill、`docs/AGENTS.md`、i18n 契约集、实操手册、issue 与 pull-request 模板、两份 `.hdsh` manifest 种子、策略 `config.json`、prek 块、`.gitattributes` 行。链接解析到已装集合之外的镜像 Markdown 在接入时改写为带 tag 的上游 URL——按侧改写，中文文档因此仍链接其中文上游；已装集合内部的链接保持相对形态。

双语配对——RFC 规则、i18n 契约、翻译规则、实操手册，以及模板化的 `architecture.md` 与 `development.md`——写入后在消费方仓库记录，其一致性记录描述的是改写后的字节而非本仓库的。一份「采纳决策」RFC 三件套脚手架连同渲染好的接入参数落在 `implemented/process/`。

模板物料——`docs/architecture.md`、`docs/development.md`、根 `AGENTS.md`——以模板分发，消费方专属内容是 `TODO(adopt):` 占位符：可 grep、每条附一行补全指引、绝不占据链接目标位置，模板因此到达即门禁合规。根 `AGENTS.md` 已存在说明消费方已在建设 agent 基础设施：adopt 跳过该模板、不报错、明说跳过，把 harness 指针并入既有文件的工作留给消费方的 agent；模板自带 reviewing skill 所链接的 `run-relevant-checks-locally` 锚点。

### adopt manifest 持有升级

`.hdsh/adopt.manifest.json` 记录 hdsh 版本、钉住的 ref、每个上游持有文件的摘要、以及消费方可补全目标清单。`verify` 对前者核对摘要、对后者清点占位符——补全占位符是预期的变更，不是漂移。新版 hdsh 下的 `apply` 重放两侧均未改动的文件，跳过已补全的占位模板，拒绝被消费方改过的生成文件并给指引。生成文件归上游所有：消费方把改动引回上游。

### ADOPT.md：非机械的一半

根目录文档 [ADOPT.md](../../../../ADOPT.zh.md) 是 i18n 契约下的双语配对（bilingual pair），是文档标准里的新 tier：消费方侧操作手册，与 CONTRIBUTING、SECURITY 同为祈使式命名。它是路由器——按序分阶段，每阶段前置条件、动作、verify 命令——并承载无法机械化的部分：git 外状态清单（标签体系、Project board 字段与状态、secrets 与 variables、分支保护），以 `gh` CLI 命令的形式交给消费方 agent 执行、由人确认，外加完成接入所需的 README 配对与占位符补全。根 `ADOPT.md` 与 README、社区文件并列，作为根级配对文档进入配对语料。

### 语料需要的引擎支持

配对结构签名中，绝对 `.zh.md` 文档 URL 现按其 `.md` 锚点形态比较，与相对语料链接既有的 locale 归一化镜像——接入改写会把两侧的上游引用改写成各自的 locale 后缀。[领域图 RFC](../architecture/2026-09-07-domain-packages-and-unified-cli.zh.md) 在同一变更中加入 adopt 域。

### 版本锚

action 安装的引擎、adopt 携带的模板、manifest 的升级全部钉在同一个 git ref 上（`--hdsh-ref`；本仓库自持用 default branch），直到首次 PyPI 发布；`ADOPT.md` 以这套措辞写明引导与升级命令。

## 验证

`tests/adopt/` 在真实临时仓库上钉住 plan/apply/verify 往返（含预先配对的消费方 README、写入后的配对记录、以及 apply 之后全语料配对检查通过）、幂等重放、ref 升级替换未改动文件、拒绝被消费方改动的生成文件、根 AGENTS 跳过规则、每一个预检阻塞、manifest 加载器的失败形态、prek 块与 `.gitattributes` 的文本手术、按 flavor 的 token 渲染、含围栏代码块的链接改写规则、以及镜像等价门禁。`tests/pairing/` 钉住根 `ADOPT.md` 的语料范围与绝对 URL 锚点归一化；policy 测试钉住 action 依赖的配置-事件交叉验证。

## 备选方案

**仅文档接入。** 有指南没有命令，每个消费方手工拼装同一套文件；没有任何东西校验结果，漂移不可检测——本记录要关闭的正是升级抱怨。

**adopt 时从 git 仓库拉取模板。** 给安装时点引入网络依赖与供应链面；包数据分发的就是消费方装下的那个版本，无需信任任何拉取。

**无 manifest 的一次性脚手架。** cookiecutter 式生成没有第二幕：没有任何东西把后一次运行与第一次相比，升级退回手工对 diff。

**对每个已装文件统一查摘要。** 占位模板就是拿来补全的；钉住其摘要会把预期变更当作漂移，manifest 因此把上游持有的摘要与消费方可补全目标分开。

**可配置的语料目录。** 配对发现读取所有 README 加 `docs/**` 与 `.agents/rfcs/**`；把目录做成配置面是为回避一个 harness 有理由规定的约定而扩大 manifest 面。接入把前置条件说清楚，而不是把它做成配置。

## 后果

- 消费方仓库经 `hdsh adopt apply`、自己的 README 配对与占位符补全后，各文档门禁全绿；升级是机械重放，而镜像语料让每份被镜像文档有了两份拷贝，由一道执行级门禁看守一致性。
- 十个 skill 的迁移把 skill 散文变成分发产品；行为性编辑从此携带消费方升级后果，其边界由 adopt manifest 圈定；被镜像文档的编辑必须同步包内拷贝，否则等价门禁失败。
- 占位符清点可以被「删除」而非「补全」清空；verify 在清点之外要求各门禁全绿，被掏空的模板会在别处失败而不是静默通过。
- adopt 的预检验证不了 git 外状态——Project board、标签、secrets——绿了的接入仍可能坐在一个未配置的仓库上，直到 ADOPT.md 清单由人确认。
