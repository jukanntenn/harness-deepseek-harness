# RFC: 配对合并驱动的 CLI 入口

Status: implemented

[English](2026-09-17-pairing-merge-driver-cli-entry.md) | 中文

## 问题

`hdsh worktree install` 曾把配对合并驱动（merge driver）注册为 `scripts/pairing-merge-driver.sh %O %A %B %P`——一个相对仓库根的路径，只在本仓库内可解析。在任何其他仓库里运行，安装器写下的驱动指向一个不存在的文件，第一次触及 `.i18n.yaml` 记录的合并就以 git 的 merge-driver 错误失败，而不是被解析或降级。包装脚本的唯一职责——运行时不可用时 fail-closed 退化为普通文本冲突——只是几行 shell 包着一个 `exec`，被 exec 的 Python 解析器本来就住在 CLI 里。配对契约的外部接入因此卡在一个无法随包旅行的仓库内脚本上。

## 决策

### 驱动变为一枚命令叶子

`hdsh pairing merge-driver` 接收 `%O %A %B %P` 四个参数，把包装脚本的语义收进 Python：仓库感知的解析器可用时，与此前 `hdsh pairing merge` 的四路径形态完全一致地解析；不可用时，命令经 `git merge-file` 写出普通文本冲突（以记录路径为冲突标签），打印恢复指引（环境恢复后运行 `hdsh pairing merge --resolve`，或 `git merge --abort`），并以非零退出让 Git 保持 index 各 stage 不被解决。`scripts/pairing-merge-driver.sh` 删除，`hdsh pairing merge` 只保留 `--probe` 与 `--resolve`，[双语配对门禁 RFC（决策记录）](../process/2026-09-07-bilingual-pairing-gate.zh.md)与领域图 RFC 已在同一变更中更新。

### 注册的命令及其前置条件

安装器写入 `uv run --no-sync hdsh pairing merge-driver %O %A %B %P`：Git 以仓库根为工作目录调用合并驱动——与此前相对脚本路径所依赖的假设相同——项目环境从该目录解析。现有探针（`hdsh pairing merge --probe`）不变。一个干净的前置条件取代包装脚本的降级路径：hdsh 已安装且环境已 `uv sync`，驱动即工作；前置条件不满足时，驱动命令本身失败，Git 以驱动错误停止合并，环境恢复后 `--resolve` 收尾——与 shell 包装脚本提示里的恢复路径相同。

### 注册串的一代迁移

以旧脚本路径注册的 worktree 在升级前继续工作。安装器识别自家被取代的驱动串并原位改写，同时照旧拒绝真正外来的 `merge.hdsh-pairing.*` 值；注册变更清单现在记录旧值，安装失败时把迁移回滚到旧串而不是清空它。升级无需任何消费方手工编辑 git config。

### 随决策同行的契约注记

没有 `.gitattributes` 里声明 `merge=hdsh-pairing` 的那一行，驱动永不运行，记录按纯文本合并：不相邻的逐行改动干净组合但无结构校验，同条目改动以普通文本冲突。配对门禁在任何情形下都是显性失败（fail-loud）的兜底——过期 hash 与结构分叉的配对在提交与 CI 变红。驱动买到的是合并时点的验证与更早、更精确的失败；记录的正确性从不依赖它。[docs/i18n/README](../../../../docs/i18n/README.zh.md) 载有这段。

## 验证

`tests/pairing/test_merge.py` 以真实 `git merge` 驱动注册后的命令：可用运行时下的组合与提交、合并分支新增的链接目标、结构分歧时降级的普通文本冲突（标记形态与干净但未经核实的记录形态）、经 `--resolve` 的恢复、pre-merge-commit 拒绝路径，以及解析安全配对并聚合所属冲突的混合合并；单元级用例钉住回退的冲突标签、路径不可读与 git 缺失时的硬失败诊断、以及 `merge` 与 `merge-driver` 的用法分界。`tests/worktree/` 钉住全新注册、旧串迁移、安装失败时回滚到旧值、以及对外来驱动值的持续拒绝。

## 备选方案

**在自有钩子目录里生成 shim。** 让 shell 包装在没有项目环境时也能工作，代价是多出第二个需要持有、回滚、升级的产物——而包装运行时仍然 exec 同一个 Python 解析器，实际什么也没解耦。

**裸 `hdsh` 驱动串。** 把合并时点行为与项目环境解耦，但要求 PATH 上装有 hdsh（`uv tool install`）——多出第二种安装拓扑要文档、要探测、要与配对工作流所声明的项目环境之家保持同步。

**从 site-packages 引用包数据脚本。** 环境重建与多环境并存让绝对路径不稳定；指进某一个 virtualenv 的驱动恰在环境最动荡时断裂。

**保留脚本并文档化复制。** 复制分发正是本变更要消除的漂移问题；且在复制到位前，每个消费方的安装器写的都是坏路径。

## 后果

- 注册的驱动串随包旅行：任何运行 `hdsh worktree install` 的仓库都得到可用驱动，升级机械地迁移该串。
- 未同步环境中的合并以驱动错误停止，而不是预写好的冲突标记——以之换取干净的前置条件；经 `--resolve` 的恢复不变，开发指南继续建议先 `uv sync`。
- 驱动串用 `uv run --no-sync` 把合并时点行为绑定到项目环境；工具安装的 hdsh 而环境未同步时走驱动错误路径。
- 迁移窗口只认识一代被取代串；更旧的或手改的值拒绝并给指引，不做猜测。
