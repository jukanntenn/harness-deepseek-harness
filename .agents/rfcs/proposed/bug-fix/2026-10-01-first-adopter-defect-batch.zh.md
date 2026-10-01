# RFC: 修复首批接入方的缺陷批次

Status: proposed

[English](2026-10-01-first-adopter-defect-batch.md) | 中文

## 问题

hdsh 首次接入真实消费方仓库时暴露了八个缺陷，全部来自实机观察而非假设。它们横跨配对门禁、被接入的 GitHub 接线与 adopt 的冲突处理，合起来破坏了门禁存在的根本承诺：每个被执行的检查只讲一个事实，错误配置在最早可解析处以响亮方式失败。

- **配对状态账本分裂。** `hdsh pairing verify` 拒绝结构签名发散的配对，但 `hdsh pairing list` 把同一配对报成 `ok`：结构差异位点只写错误账本、不写配对状态，兜底逻辑于是标绿。任一侧缺失语言切换器也带着同样的缺陷。
- **composite action 从消费方自己的 clone URL 安装引擎。** 两个 action 都用 `github.event.repository.clone_url` 解析引擎仓库，而这个上下文值在消费方 workflow 里指向消费方仓库；钉住的 ref 在那里不存在，第一个 policy 或 lifecycle 事件在安装引擎一步即告失败。本仓库自己的 workflow 从不执行这两个 action，消费方路径因此从未被证明；本 RFC 修正的是 [composite action RFC](../../implemented/feature/2026-09-17-issue-policy-composite-actions.zh.md) 已发布的设计。
- **切换器语法拒绝更精确的标签。** 语言切换器行只接受字面 `中文` 标签，于是 `简体中文`——对 zh-Hans 更精确的名称——被判为缺失切换器，尽管切换器就在原处且写法正确。
- **带 --group 过滤的 CI 静默地一个托管 hook 都不跑。** prek 的 `--group` 过滤会排除无组 hook，adopt 托管块恰好全都没有组，于是按自家分类过滤的消费方 CI 一个 hdsh 门禁都不执行，而本地无过滤运行六个全跑：本地红、CI 绿、任何地方都没有报错。
- **merge driver 静默退化。** `hdsh worktree install` 注册的 driver 命令硬编码为 `uv run --no-sync hdsh pairing merge-driver`，其探测跑的是安装进程自身的形态而非注册的那个；在 PATH 上没有 hdsh 又没有项目环境的机器上，每次配对记录合并都静默回退到 Git 的文本合并。注册机制见 [merge driver RFC](../../implemented/feature/2026-09-17-pairing-merge-driver-cli-entry.zh.md)。
- **既有 standing docs 没有合并路径。** 冲突的根 `AGENTS.md` 会被跳过并给出合并提示，但语料链入它的深链锚点在消费方文件里并不存在，消费方自己的 links 门禁因此无引导地红一半——一个锚点失败，另一个碰巧命中同名标题。其余 standing docs（今天的 `docs/AGENTS.md`）则干脆是硬性 clobber blocker 而非跳过。
- **链接改写器改坏行内代码示例。** 裸正则改写器把反引号代码段里形似链接的文本当链接，改写成上游也不存在的文件的上游 URL：示例被撑坏、链接已死，而任何门禁都看不见。
- **actionlint 的 schema 滞后只在下游暴露。** hdsh 的 CI 从不跑 actionlint，actionlint 内置 schema 与 GitHub 接受的活动类型（`issues.field_added`、`field_removed`）之间的滞后只能被每个消费方各自重新发现一次。

## 提案

**D1——统一状态账本。** 配对检查里的每个错误位点都写下它隐含的配对状态：结构发散、任一侧缺失切换器或 record 畸形标 `out-of-sync`；不完整配对标 `missing`；只有零错误的配对是 `ok`。`list` 与 `verify` 从此读同一本账。

**D2——从 action 自身的仓库安装引擎。** 两个 composite action 改用 `github.action_repository`（承载 action 的仓库）解析引擎仓库，本地 uses 场景回退到事件仓库；另加一个 CI 彩排 job 按消费方 workflow 的方式原样执行这两个 action，让消费方路径在每次变更时都被证明，而不是从未被证明。

**D3——接受两种切换器标签。** 切换器语法在两个标签位独立接受 `中文` 或 `简体中文`；hdsh 自有语料继续统一写 canonical 的 `中文`，这是门禁刻意不强制执行的风格规则。

**D4——托管块自带组。** 每个托管 prek hook 生成时都带 `groups = ["hdsh"]`，plan 输出与接入手册同时声明：使用 `--group` 过滤的 CI 必须包含 `hdsh` 组。

**D5——探测什么就注册什么。** `hdsh worktree install` 通过探测可能注册的形态来解析 driver 命令——先探测裸 `hdsh` 形态，再探测面向项目环境机器的 `uv run --no-sync` 形态——注册第一个解析成功的形态并打印所选形态；两者都解析不到则以安装引导响亮失败。

**D6——跳过、跟踪、点名锚点。** 冲突的 standing document 被跳过并登记为待手工合并；adopt verify 从语料链入该文件的链接计算所需锚点集合并逐个点名缺失项；合并落地后 links 门禁继续作为永久看守。链入被跳过文件的链接保持相对——不做上游改写。

**D7——代码段永远不是链接。** 改写器跳过行内代码段，示例文本逐字节原样落入消费方仓库。

**D8——上游跑 actionlint。** hdsh 的 CI 运行 actionlint，让 schema 滞后在 workflow 的出产地被抓住；接入手册记录消费方的缓解措施及其移除条件。

## 验证

每个修复都伴随聚焦测试，证明坏案例修前失败、修后通过：结构发散的配对让 `list` 与 `verify` 得出同一结论；消费方形态的彩排从 hdsh 仓库安装引擎；两种切换器标签都通过配对门禁；加上组之后带过滤的 prek 运行执行每个托管 hook；无可运行 hdsh 的机器上 worktree install 以非零退出并点名安装步骤；adopt verify 逐个列出缺失的 harness 锚点；行内代码示例逐字节落地；CI 的 actionlint 步骤把 schema 滞后报为上游失败。

## 备选方案

**把被跳过文件的链接改写为上游 URL（D6）。** 否决：这会重新引入语料计划正在消除的对 hdsh 的出站依赖，而消费方 review 流程里指向 hdsh standing orders 的指针恰恰是该计划要堵住的泄漏。

**检测 pyproject.toml 再选 driver 形态（D5）。** 否决：调用正典已经写明解析顺序，检测等于用第二套机制复述它；按正典顺序探测、注册第一个解析成功的形态，让探测账本与注册账本合而为一。

**用可编辑槽位做每仓库的组名（D4）。** 否决：存在普适值——任何带过滤的 CI 都能加 `--group hdsh`——所以这不是每仓库值，槽位只会引入无人需要的持久化机制。

**每个缺陷一篇 RFC。** 否决：每个修复单独看都在机械豁免线上或线内；它们共享一篇记录是因为共享同一个出处——一次接入——整批判审比八次上下文切换便宜。

## 验收标准

- `hdsh pairing list` 与 `hdsh pairing verify` 在每种状态下对每个语料配对得出一致结论。
- 消费方仓库的第一个 policy 或 lifecycle 事件从 hdsh 仓库按钉住的 ref 安装引擎。
- 切换器写 `简体中文` 的配对无需修改即通过 `hdsh pairing verify`。
- 加上 `--group hdsh` 后带过滤的 prek 运行执行每个托管 hook，且托管块无需消费方修改即携带组。
- 没有可运行 hdsh 的机器上 `hdsh worktree install` 以非零退出并附带安装引导。
- 对被跳过的 standing document，adopt verify 逐个点名缺失的 harness 锚点，引导合并完成后每个锚点都可解析。
- 行内代码示例逐字节原样落入消费方仓库。
- actionlint 在 hdsh CI 中运行，文档记录的消费方缓解措施附带移除条件。

## 风险

- D6 把硬性 clobber blocker 变成被跟踪的待合并项，adopt 运行现在可能在 standing document 仍欠内容时就成功；该待办会留在之后每次 adopt verify 的输出里直到合并落地。
- D4 要求带过滤的 CI 多加一个 flag；忘记加的消费方仍会踩旧的静默缺口，这正是 plan 输出与手册同时声明该要求的原因。
- D3 接受同一配对内混用两种标签变体；风格规则保持 hdsh 自有语料的 canonical 形态，门禁刻意不裁判品味。
