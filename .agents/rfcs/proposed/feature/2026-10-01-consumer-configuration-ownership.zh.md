# RFC: 把配置文件的所有权交给消费方

Status: proposed

[English](2026-10-01-consumer-configuration-ownership.md) | 中文

## 问题

三个被安装的文件把上游渲染的字节与每仓库值混在一处，而 adopt manifest 按字节钉死它们：`.hdsh/pairing.manifest.json`——其 `excluded`、`generated`、`public_blob_root` 三个字段是文档明载的消费方机制——加上 `.hdsh/docs.manifest.json` 与 `.github/issue-management/config.json`。第一个按文档行使机制的消费方（把 `.zcode/README.md` 排除出语料）落进永久死锁：adopt verify 永远报 drift，之后的 re-apply 被 clobber 检查拒绝，而其引导——还原本地改动、或把改动重定向上游——对仓库专属的排除项根本不可执行。根因在所有权而非钉死：这些文件里的种子项（英文单语排除集、标准 wrap 与 links glob）是穿着配置外衣的语料常量，字节钉死在保住种子的同时把消费方的值一并扣押。同样的钉死让改一个 Project 编号或时区变成全部生成文件的完整重跑。被扩展的配置面归[配对门禁 RFC](../../implemented/process/2026-09-07-bilingual-pairing-gate.zh.md) 与[文档语料门禁 RFC](../../implemented/process/2026-09-07-document-corpus-gates.zh.md) 所有；绑定行为归[引导式接入 RFC](2026-10-01-guided-adoption-wizard.zh.md)。

## 提案

- **种子迁为语料常量。** 英文单语排除集与标准 wrap、links glob 从 manifest 迁入门禁的范围谓词——协议常量，而非随部署变化的 tunable——pairing manifest 由此以纯消费方配置的形态出生。模板化 standing docs 的初始字数预算作为一次性初值留在文件里。
- **三个文件归入可编辑类。** 创建一次，永不按 digest 钉死，永不参与 clobber 检查，re-apply 不再触碰。adopt verify 以结构化检查替代字节钉死：加载时校验，加上对 adopt 拥有字段的交叉核对——owner、repository、account type 对照推导结果，statuses 对照标准集，Project 编号对照 manifest 锚点。
- **pairing manifest 新增 `roots`。** 每个条目按 `excluded` 已在使用的尾斜杠边界规则以子树前缀扩展语料；这是对"自有双语文档树位于标准范围之外的消费方仓库"的修复：其 README 指向自身内容的链接不再按字节比较而发散，而是像语料链接一样归一化。
- **手写的 `config.json` 是合法的绑定输入。** 旗标与既有文件值矛盾即为 blocker——不猜优先级——消费方拥有的字段是自由编辑，在加载时校验。

## 备选方案

**基线加覆盖的双层文件。** 否决：它是把混合所有权问题归档而不是消解。种子迁走后这些文件里不再有任何上游字节，第二层失去存在理由，剩下的只是维护"不存在"的新机制。

**保留字节钉死并文档化"把改动重定向上游"。** 这正是首个消费方实际撞上的死锁；仓库专属的排除项无处可重定向，而死锁恰恰是严格照文档操作的结果。

**可编辑但种子原地保留。** 否决：混合所有权才是根因。消费方可能静默删掉某条种子排除，直到下游配对失败才知道——离行为本身隔了一步。

## 验收标准

- 新增排除项、新增 `roots` 条目、改正 Project 编号或时区，都不再造成 adopt verify 的 drift，也不再阻塞 re-apply。
- 删除必填字段在加载时校验失败并点名该字段。
- adopt 拥有的字段与推导结果或锚点矛盾时，成为被点名的 blocker。
- 种子迁移不改变标准集的语料行为：同样的文件留在范围内，同样的门禁覆盖它们。

## 风险

- 失去对这些文件的 digest 钉死会削弱漂移检测；被点名的结构化检查是替代品，其覆盖面——加载校验、推导一致、锚点一致——是被枚举的而非隐含的。
- 种子迁移一次性改变 manifest 内容，升级因此携带一个必须写进发布说明的一次性迁移步骤。
- 消费方拥有的 `roots` 条目把每条配对规则——包括结构签名比较——扩展到 hdsh 从未见过的一棵树上；这正是机制按设计运转，但它扩大了错误声明一个 root 能影响的范围。
