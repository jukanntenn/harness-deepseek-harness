# RFC: 校验 worktree 钩子接管，而不是信任 prek 的安装默认值

Status: implemented

[English](2026-10-05-worktree-hook-takeover-validation.md) | 中文

## 问题

`uv run hdsh worktree install` 接管 `core.hooksPath` 后把其余事项交给一条裸 `prek install --overwrite`，留下三条钩子静默停跑的路径。其一，prek 只安装其配置声明的 hook type：没有 `default_install_hook_types` 时裸安装只写一个 `pre-commit` stub，而 hdsh 从未替消费方声明过这个键。其二，接管遗弃了默认 `.git/hooks` 目录里既有的活跃原生钩子——`core.hooksPath` 一移动，消费方的 pre-push 覆盖率门禁与 commit-msg 校验就直接停止执行，安装时无警告、事后无诊断。其三，没有任何步骤核验实际落盘了哪些 stub。第四个接入方撞上的正是这个组合：接入后 pre-push 与 commit-msg 门禁消失，靠手工恢复。其报告把损失归因于 prek 0.4.11 无视 TOML 中 `default_install_hook_types` 的 bug；该 bug 的净室复现失败了——0.4.10 与 0.4.11 都尊重该键——但归因不改变缺陷本身：接管的可观察正确性依赖了未经验证的安装期行为，而这正是本 harness 要消灭的「门禁静默退出」失败模式。被修复的接管设计见[本地 Git workflow RFC](../process/2026-09-07-local-git-workflow.zh.md)。

## 决策

- 从消费方 `prek.toml` 读取声明的 hook type 集合：键缺失即 prek 自身的默认（`pre-commit`），完全没有 `prek.toml` 则集合未知。畸形或空声明在安装期显性失败。
- 把完整声明集以显式 `--hook-type` 旗标传给 `prek install`。经对 prek 0.4.11 实测证明：旗标是替换而非追加配置列表——所以必须携带全部声明类型；携带它们使安装不再依赖运行中的 prek 是否尊重 TOML 键。未知集合（yaml 配置、无配置）保持裸调用，而不是靠猜测收窄任何东西。
- 安装之后，每个声明类型都必须在受管钩子目录里拥有 stub 文件，否则安装失败、接管回滚。
- 全新的接管——任何作用域都没有生效的 `core.hooksPath`——先扫描默认钩子目录（`git rev-parse --git-path hooks`）中的可执行非 sample 原生钩子并拒绝，逐个点名并给出两条出路：经 `prek.toml` 链入（对应 stage 的 hook 条目加上 `default_install_hook_types`），或带 `HDSH_PREK_ALLOW_ORPHANED_HOOKS=1` 重跑以承认其停跑。prek 与 pre-commit 生成的 shim 豁免——向受管目录重装即取代它们——已受管的生效 hooks path 不再重扫，重跑保持幂等。

## 验证

单元测试钉住声明解析（存在、默认、缺失、畸形）、裸调用与声明调用的旗标构造、stub 校验，以及孤儿扫描（可执行位、`.sample` 名、两种工具 shim 标记、子目录、缺失目录）。假 prek 端到端套件对着真实 Git 证明接管契约：被丢弃的声明类型使安装失败且 hooks path 回滚；未获承认的原生钩子阻断接管且原文件不动；工具 shim 与已接管的目录不阻断；无配置的仓库裸安装、不做校验。

## 考虑过的替代方案

**无条件枚举全部 hook type。** 否决：这会安装消费方从未声明的 stub，而且——因为旗标替换配置列表——会把 prek 配置刻意收窄的安装重新拓宽，恰是被修缺陷的镜像。

**继续信任 `default_install_hook_types` 的处理。** 否决：第一份现场报告的到来，正是因为接管既无证明也无守卫；某个 prek 版本是否尊重 TOML 键，恰恰是被执行的不变量不该依赖的外部行为。

**对孤儿原生钩子警告而非拒绝。** 否决：安装期的警告一滚而过，而它预言的失败——门禁静默停跑——是本仓库分级最高的那类；拒绝为深思熟虑的场景留了显式承认的出口。

**自动把原生钩子迁移进 prek.toml。** 否决：替消费方写 hook 条目是在猜测其环境、顺序与 stage；链接一个钩子是消费方的决定，拒绝信息只指路、不代劳。

## 后果

换来的是：每次接管都被证明完整——声明类型有 stub，否则安装回滚——消费方的既有门禁再也不会静默消失在一移动的 `core.hooksPath` 背后；失败模式在安装期浮出并点名补救动作。

付出的是：持有活跃原生钩子的消费方在首次安装前多出一个显式步骤（链入或承认），而 prek 配置为 yaml 而非 TOML 的仓库在出现 yaml 读取器之前保持裸安装、不做校验——这一类已被接入路径阻断，受管语料不受影响。
