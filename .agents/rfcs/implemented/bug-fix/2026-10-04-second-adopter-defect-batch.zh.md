# RFC: 修复第二批消费方缺陷

状态：已实施

[English](2026-10-04-second-adopter-defect-batch.md) | 中文

## 问题

对首次完成接入的仓库——wakewake——的评审暴露出第二批缺陷，同样来自实际观察而非假设。它们集中出现在 adopt 自身机制与契约相矛盾之处：不可能通过的探针、读错远端的推导、只覆盖一半路径的变换，以及手册声明了却没有任何已执行检查强制的不变量。

- **preflight 的 hdsh 探针不可能通过。** 向导用 `hdsh --version` 证明可运行性，但 CLI 未注册 version action，于是刚装好的 hdsh 以退出码 2 失败，preflight 报 `bare hdsh is not runnable on PATH`——手册文档化流程的第一步在健康机器上必红，且修复建议指向尚不存在的 PyPI 包。
- **ref 推导读的是消费方的远端。** `resolve_hdsh_ref` 在消费方仓库内执行 `git ls-remote --tags origin`，自带 `vX.Y.Z` tag 的消费方会把自己的某个 tag 静默写进 hdsh 仓库的 prek `rev`；克隆在远离 apply 之处失败。
- **接入日期无视 `--time-zone`。** apply 以 UTC 为带日期的记录盖章，Asia/Shanghai 本地 2026-10-03 06:14 接入的操作者拿到 `2026-10-02` 的决策记录——与操作者的日历差一天。
- **被 root 进语料的 agent 指令被要求翻译。** 英文豁免是六个硬编码路径；manifest `roots` 子树自带的 `AGENTS.md` 立即欠一篇中文对侧，唯一出路是逐文件打 `governed` 豁免。
- **语料外的双语链接无法同时满足两条规则。** locale 约定要求每侧链接自己的后缀（`.md`／`.zh.md`），但结构签名对语料外相对目标按原始字节比较，仅遵循约定就必然发散；首个接入方踩到三处，只能把整棵旧子树 root 进语料才脱身。
- **手册严重低估配对工作量。** 阶段 3 只说「为仓库自己的 README 配对」；发现机制会找出任意深度的每对 README 加上 root 子树——三十对，不是一对。
- **actionlint 桥接不随 apply 下发。** 手册让消费方「用 `paths.ignore` 过渡」，但 apply 不写桥接文件，且 schema（按文件、按消息正则）全靠猜；首个接入方写错两版后才照抄 hdsh 自仓的。
- **组过滤的 CI 仍在静默丢门禁。** 托管钩子带 `hdsh` 组、手册有警告，但没有任何机制执行该警告：首个接入方的范围化 lint job 过滤时缺 `hdsh`，其路径下的门禁无处运行。
- **invocation 映射只覆盖一半渲染路径。** 槽位模板与 token 渲染模板跳过 `map_invocations`，`uv run hdsh scope` 因此留在 reviewing skill 里，七个 `uv run hdsh` 形态留在全新写入的 `docs/AGENTS.md` 里。
- **移植技能带着 harness 品牌。** 七处 "harness-deepseek-harness" 字符串、"hdsh documentation" 标题、以及 `src/hdsh/` 语料事实落进了消费方的技能树；没有任何机制承载消费方自己的事实。
- **ripgrep 被默认使用却从未被检查。** 各 skill 指令「优先 `rg`」；preflight 只探测 git、gh、hdsh。

## 决策

**D1——CLI 回答自己的探针。** 根 parser 从已安装发行版注册 `--version`；parser 退出契约泛化为 `InfoShown`，help 与 version 同等；preflight 修复建议与 worktree 驱动提示在 PyPI 发布前均指向 `git+<url>@<ref>` 安装形式。

**D2——ref 推导直读上游 URL。** `resolve_hdsh_ref` 直接从 `https://github.com/jukanntenn/harness-deepseek-harness` 列 tag，绝不读消费方的远端；无 main-HEAD 回退的失败语义保持不变。

**D3——带日期的记录遵循 Project 时区。** 接入日期由解析后的 `--time-zone` 推导（缺省时来自系统时区）；旗标帮助文案写明这一点。

**D4——agent 指令按类规则仅英文。** 任何 `AGENTS.md` 按模式排除——在 `roots` 扩展之后做减法，root 子树因此无需逐文件豁免；翻译记忆参考文件仍是仅有的路径常量。

**D5——语料外链接按英文锚点比较。** 活跃语料之外的相对目标在结构比较前投影到其 `.md` 形态——绝对 URL 规则的相对版本——仅每侧 locale 约定不再可能使配对发散；locale 检查继续治理语料内目标。

**D6——apply 为配对语料测量规模。** plan 与 apply 对 apply 后的语料打印一行说明——范围内英文文档数、仍缺对侧与记录的数量——阶段 3 写明真实语料形状：任意深度的每对 README、`docs/**`、`.agents/rfcs/**`、以及 manifest `roots`。

**D7——actionlint 桥接随 apply 下发。** `.github/actionlint.yaml` 成为镜像文件：按文件、按消息正则的桥接，附移除条件与 GitHub 官方文档所列 `issues` 活动类型的链接；既存副本响亮阻断而非被覆盖。

**D8——verify 执行 CI 组契约。** `hdsh adopt verify` 扫描 workflow 文件中 `--group` 过滤缺 `hdsh` 的 `prek run` 命令，并逐条报为漂移；该检查经 `hdsh-adopt-verify` 钩子在 CI 中执行。

**D9——一个 invocation 变换，覆盖全部渲染路径。** `map_invocations` 运行于 token 渲染模板与槽位解析前的槽位模板——指导语 digest 保持稳定，因为没有任何指导语正文携带源形态——verify 将 adopt 所管文件中的任何 `uv run hdsh` 残留报为漂移。

**D10——移植技能不携带 harness 品牌。** 活技能措辞去掉仓库名与品牌标题（"this repository"、"# Archive RFCs"、"# Documentation"）；`finding-simplifications` 从镜像集迁入槽位模板，以 `production-corpus` 槽承载其判断性事实。

**D11——ripgrep 加入 preflight。** `rg --version` 是第四个探针；成功提示行与手册均写明。

## 验证

聚焦测试钉住每条路径：`hdsh --version` 打印已安装版本并以 0 退出；ref 推导绝不查询消费方 origin 的 transport 键；同一冻结时刻在 Asia/Shanghai 比 America/New_York 晚一天；被 root 的 `.agents/wrfcs/AGENTS.md` 留在语料外而同子树的 README 进入语料；语料外 `.zh.md` 目标与其 `.md` 对侧判等、真正不同的目标仍发散；apply 输出携带语料规模说明与含依据链接的 actionlint 桥接；缺 `hdsh` 组的 workflow 在其文件与行号处报漂移，补组或去过滤后转绿；槽位模板与 `docs/AGENTS.md` 以裸形态落地（`hdsh scope`，无 `uv run hdsh`），手工引回的源形态报漂移；移植技能不含 "harness-deepseek-harness"；缺 `rg --version` 的 transport 报一条诊断。

## 考虑过的替代方案

**在移植时映射仓库名（D10）。** 否决：镜像必须与活文件字节相等，变换层映射要么破坏 hdsh 自身副本、要么使活文本与移植文本分叉；把活文件措辞改为仓库中立保持单一真源。

**为英文豁免文件增加 manifest 键（D4）。** 否决：该豁免是 agent 指令的类不变量，不是随部署变化的选项；一个键会诱使类规则本可免除的逐文件豁免。

**缺组时警告而非漂移（D8）。** 否决：警告通道正是 harness 要关闭的静默空间；范围化 job 补 `--group hdsh` 没有代价。

**独立的 `--date-zone` 旗标（D3）。** 否决：Project 时区就是仓库的日历；两个时区旗标会让带日期的记录与 Project 渲染按设计不一致。

## 后果

本批换来的：全新机器首次 preflight 即绿；带 tag 的消费方无需传 `--hdsh-ref` 即可接入；决策记录携带操作者的日期；root 子树无需指令豁免；语料外双语链接在 locale 约定下直接通过，无需把旧树 root 进语料；apply 打印真实配对工作量；actionlint 桥接与依据随 workflow 一并到达；缺组的过滤 CI 在 verify 变红；移植文件只携带裸调用形态；消费方技能树冠以自己的仓库名，`finding-simplifications` 通过槽位询问自己的生产语料。

本批的代价：既有接入方重跑 apply 会以槽位版替换 `finding-simplifications` 并欠一个新的占位符；手写的 `.github/actionlint.yaml` 会阻断重新 apply，直到删除（响亮、一次性）；ADOPT.md 词数上限上调（英文 470→740、中文 190→270），因为手册新增退役章节与真实语料形状；`--time-zone` 多了一重职责——Project 渲染与带日期的记录共用一个日历，而这正是目的。
