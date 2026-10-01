# RFC: 推导接入参数并为 git 外设置设门禁

Status: proposed

[English](2026-10-01-guided-adoption-wizard.md) | 中文

## 问题

`hdsh adopt plan` 要求六个旗标，其对应事实消费方大多无法从命令行得知，且接入手册的 Phase 2 是工具看不见的人工清单；被扩展的已发布设计见 [adopt RFC](../../implemented/feature/2026-09-17-hdsh-adopt-and-templates.zh.md)。失败来得晚、落点最糟：错的 Project 编号在仓库第一个 issue 事件上爆炸，账户类型不匹配在每次 workflow 运行里失败，缺失的 gh 或其 stack 能力要等到镜像技能硬停那一刻才被发现，而标签分类、看板形状、机密这些没有任何地方校验。首次接入方需要一场调试会话才能发现工具本可以检查的东西：参数可推导、GitHub 状态可查询、gh 与 hdsh 本身可探测。

## 提案

### 参数解析

- `--account-type` 从 origin remote 的 owner 类型推导；非 github.com 的 origin 仍是 blocker。
- `--hdsh-ref` 默认取上游最新正式版 tag，不存在则响亮失败——上游发布纪律是声明过的前提，且刻意不做 main-HEAD 兜底。
- `--lifecycle-actor` 从 Project 凭据的身份推导，因为该凭据正是生命周期用以比对 Project 变更的那个身份；organization 形态下在 App 创建时捕获。
- `--time-zone` 默认取操作者本地系统时区；GitHub 没有可读取的账户时区。
- 每个推导都在 plan 输出中回显，每个旗标仍可显式覆盖，全显式运行保持离线——封闭的 e2e 测试套件依赖这一点。

### Project 的创建与绑定

- 未配置 Project 时，向导创建标题为 `"<仓库名> Issue Management"` 的看板，带七个标准状态、Priority 字段与 Start date 字段。
- 给了 `--project-number` 或手写了 `config.json` 时，向导改为绑定：在推导出的 owner 与账户类型下解析看板，校验形状，并通过 plan 与 apply 补齐缺失的状态和字段。
- 绑定把编号写入 `config.json`，把 Project 的 node id 与标题写入 adopt manifest，作为仅供 verify 使用的锚点。
- 锚点永不自动更新：config 编号与锚点矛盾、或解析出的 node id 不再匹配，都是 blocker 级诊断，并指名显式的重绑定动作。看板改名保持自由——标题只是展示元数据，node id 才是唯一不可变、不受改名影响的把手，而运行时查询本来就取回了它。

### 凭据、标签与预检

- 凭据：user 形态是引导式的经典 PAT 步骤——平台规定必须由人完成的那一步——随后 `gh secret set`；organization 形态是 App manifest 流程（创建、生成私钥、安装），随后 `gh variable set` 与 `gh secret set`。机密、变量、令牌 scope 与身份、看板形状、标签分类的验证全部程序化。
- 标签：`kind/*` 全集、初始 `area/*`、user 账户的 `type/*` 通过 `gh` 创建；分支保护保持显式清单项，永不静默变更。
- 预检分层，每个失败一条 blocker 并附建议解法，落在现有 Blocker 账本上：本地工具链（git 2.26+、已认证且 scope 齐全的 gh、stack 能力、可运行的裸 hdsh）、远端渲染依赖（ref 可解析、hdsh 仓库可达、允许外部 action）、GitHub 侧状态（标签、看板形状、机密与变量）。
- 安装正典：消费方在主机上安装 hdsh，PyPI 发布前用 `uv tool install`，接入手册 Phase 4 据此重写；预检要求裸命令可用。

## 备选方案

**为 ref 做交互式倾向采集。** 否决：接入由 agent 执行，plan 输出就是采集面——agent 读到解析出的默认值，不同意就覆盖，然后重跑。

**无正式版 tag 时回退 main HEAD。** 否决：这会让所有早期消费方常态化运行在未发布门禁上，把上游的纪律失败静默转成消费方风险，且同一天两次接入不可复现。响亮失败是诚实的信号，也更便宜。

**用标题相等性防拿错看板。** 否决：看板标题设计上就允许消费方修改，该守卫会把每次改名变成流水线故障；node id 提供同样的防护而没有这份耦合。

**每次事件做运行时 node id 比对。** 否决：为一个人工改错的尾部风险买来常驻运行时配置字段和新的运行时失败形态；verify 时核查覆盖同一风险而运行时零成本。

**凭据全自动。** 平台的设计使之为不可能——PAT 创建与 App 注册要求所有者同意——所以自动化属于可能之处：上传与验证。

## 验收标准

- 拥有 gh 与主机安装 hdsh 的全新 GitHub 仓库，除向导按名称询问的选择外，零手输参数达到 adopt verify 全绿。
- 错误的 Project 编号在绑定时失败，诊断同时点名两种可能成因。
- 锚点不匹配时 adopt verify 失败并指名显式重绑定动作；看板改名则原样通过。
- 预检对每个缺失的工具、scope、机密、标签、看板字段响亮失败，一条 blocker 一条诊断。
- 全显式的 plan 与 apply 可离线运行。

## 风险

- adopt 获得网络与 gh 依赖；显式旗标的离线路径保住了 CI 与 e2e 套件的封闭性，代价是要测两种执行模式。
- 看板自动创建会在任何文件落地前写 GitHub 状态；plan-then-apply 纪律是守卫，且 plan 打印精确的变更清单。
- 共享机器上推导默认值可能推错——gh 登录的不是预期操作者；每个推导都被回显且可覆盖，这把暴露面限制在一次被评审的 plan 输出之内。
