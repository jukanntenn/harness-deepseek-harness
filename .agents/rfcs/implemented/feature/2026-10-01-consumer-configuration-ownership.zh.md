# RFC: 把配置文件的所有权交给消费方

Status: implemented

[English](2026-10-01-consumer-configuration-ownership.md) | 中文

## 问题

三个被安装的文件把上游渲染的字节与每仓库值混在一处，而 adopt manifest 按字节钉死它们：`.hdsh/pairing.manifest.json`——其 `excluded`、`generated`、`public_blob_root` 字段是文档明载的消费方机制——加上 `.hdsh/docs.manifest.json` 与 `.github/issue-management/config.json`。第一个按文档行使机制的消费方（把 `.zcode/README.md` 排除出语料）落进永久死锁：adopt verify 永远报 drift，之后的 re-apply 被 clobber 检查拒绝，而其引导——还原本地改动、或把改动重定向上游——对仓库专属的排除项根本不可执行。根因在所有权而非钉死：这些文件里的种子项（英文单语排除集、标准 wrap 与 links glob）是穿着配置外衣的语料常量，字节钉死在保住种子的同时把消费方的值一并扣押。同样的钉死让改一个 Project 编号或时区变成全部生成文件的完整重跑。被扩展的配置面归[配对门禁 RFC](../process/2026-09-07-bilingual-pairing-gate.zh.md) 与[文档语料门禁 RFC](../process/2026-09-07-document-corpus-gates.zh.md) 所有；绑定行为归[引导式接入 RFC](../../proposed/feature/2026-10-01-guided-adoption-wizard.zh.md)。

## 决策

- **种子迁为语料常量。** 英文单语排除集与标准 wrap、links glob 从 manifest 迁入门禁本体：`is_scope_file` 自带英文单语文件，文档门禁内置 `STANDARD_SCOPE` 标准语料。pairing manifest 以纯消费方配置的形态出生（`excluded` 与 `generated` 一样变为可选），docs manifest 的 wrap/links 段落变为可选的消费方扩展——与标准语料求并集，而非顶替它。模板化 standing docs 的初始字数预算作为一次性初值留在文件里。
- **三个文件归消费方所有。** 接入时创建一次，永不按 digest 钉死，永不参与 clobber 检查，re-apply 不再触碰；adopt manifest 在 `consumerConfig` 下列出它们，adopt verify 以结构检查替代字节钉死：每个文件必须能被其所属解析器加载；`config.json` 必须仍然指向 origin remote 的仓库并携带标准状态集。Project 编号对照锚点的交叉检查等待引入锚点的引导式接入程序。
- **pairing manifest 携带 `roots` 与 `governed`。** `roots` 条目是以尾斜杠结尾的子树前缀，用于扩展语料——自有双语文档树位于标准范围之外的消费方仓库声明它之后，其 README 指向该树的链接不再按字节比较而发散，而是像语料链接一样归一化。`governed` 条目命名由本仓库自行治理的双语内容：译文可以存在，门禁完全不看。一个谓词——标准语料或 roots，减去 excluded 与 governed——同时驱动发现、具名锚点校验与链接源语义。
- **手写的 `config.json` 是绑定输入。** 其值成为接入参数；任何与文件值矛盾的必填旗标都是 blocker——必填旗标永远是显式给出的，adopt 绝不猜优先级。`--allow-unassigned-owner` 这类 store-true 旗标无法区分显式与缺省，该布尔以文件为准。状态集偏离标准集的文件在 apply 即被拦截，而非只等 verify。

## 验证

聚焦测试逐项钉住行为：预存的消费方 manifest 在 apply 后逐字节不变，其 digest 离开 adopt manifest；手写 `config.json` 完成绑定，矛盾旗标以字段名拦截，畸形文件拦截，非标准状态集在 apply 拦截；verify 把无效、缺失、仓库不匹配的消费方配置报为 drift；`roots` 让一棵消费方文档树的跨语言链接归一化通过，而同一棵树在没有 root 时保持红；`governed` 保留译文而不施加完整性或切换行要求；文档门禁在无 manifest 段落时覆盖标准语料，并把消费方扩展并入。本仓库以瘦身后的新形态 manifest 跑全部语料门禁，全绿。

## 备选方案

**基线加覆盖的双层文件。** 否决：它是把混合所有权问题归档而不是消解。种子迁走后这些文件里不再有任何上游字节，第二层失去存在理由，剩下的只是维护"不存在"的新机制。

**保留字节钉死并文档化"把改动重定向上游"。** 这正是首个消费方实际撞上的死锁；仓库专属的排除项无处可重定向，而死锁恰恰是严格照文档操作的结果。

**可编辑但种子原地保留。** 否决：混合所有权才是根因。消费方可能静默删掉某条种子排除，直到下游配对失败才知道——离行为本身隔了一步。

## 后果

本变更买到的东西：新增排除项、新增 `roots` 条目、改正 Project 编号/时区/actor，都不再造成 adopt verify 的 drift，也不再阻塞 re-apply；删除必填字段在加载时校验失败并点名该字段；adopt 拥有的字段与推导结果矛盾时成为被点名的 blocker；种子迁移不改变标准集的语料行为——同样的文件在同样的门禁下留在范围内。

本变更的代价：失去对这些文件的 digest 钉死削弱了漂移检测，被点名的结构化检查——加载校验、仓库一致、状态集一致——是被枚举的替代品。种子迁移一次性改变 manifest 内容，升级因此携带一个旧文件可以平稳吸收的一次性迁移（种子条目与标准 glob 相对内置常量成为空操作）。消费方拥有的 `roots` 条目把每条配对规则——包括结构签名比较——扩展到 hdsh 从未见过的一棵树上；这正是机制按设计运转，但它扩大了错误声明一个 root 能影响的范围。
