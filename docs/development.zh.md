# 开发指南

[English](development.md) | 中文

安装教程带新贡献者从前置条件走到可用的 checkout。随后的贡献者参考覆盖日常工作流、Git 集成与 CI 组织。设计理由属于链接的 RFC；包的地图属于 [architecture.md](architecture.zh.md)。

## 安装教程

### 前置条件

- Python 3.12 或更新版本；CI 覆盖受支持的最低版本与当前版本。
- [uv](https://github.com/astral-sh/uv) 管理项目与锁文件。
- Git 2.26 或更新版本；worktree 本地钩子使用 Git 按 worktree 的配置扩展。

### 首次安装

从仓库根目录安装依赖：

```sh
uv sync
```

安装后配置仓库级 prek 钩子：

```sh
uv run prek install
```

如果你在堆叠的 Git worktree 中工作，改为安装 worktree 本地钩子与 `hdsh-pairing` 合并驱动——每个新 worktree 都要自行运行一次：

```sh
uv run hdsh worktree install
```

全新 clone 后把检查各跑一遍：

```sh
uv run pytest
uv run ruff check .
uv run basedpyright
```

三项全部成功退出，安装即完成。

## 贡献者参考

### 项目布局

一个名字在目录、CLI 域与 hook-id 前缀三层标识同一个概念：`src/hdsh/` 下的 `pairing/`、`docs/`、`rfc/`、`policy/`、`worktree/` 与 `scope.py`，位于单一 `hdsh` 入口之后。完整地图——域、退出码契约、新行为的去处——见 [architecture.md](architecture.zh.md)。

### Git 集成

配对合并驱动在两侧语言文件都使用 Git 默认文本策略且能干净合并时，从确认过的祖先、当前与对方所属 blob 推导出冲突的 `.i18n.yaml` 记录。它在所属文件冲突、非文本合并配置或无效记录上 fail-closed；合并已经停下之后，运行 `uv run hdsh pairing merge --resolve`，它会暂存每份可安全生成的配对记录，并在还有配对冲突需要手工处理时以失败退出。驱动接受的文件与状态的精确定义见[双语文档契约](i18n/README.zh.md#the-pairing-contract)。

驱动运行时不可用时，shell 启动器降级为纯文本合并并以 1 退出，Git 因此保持索引阶段未解析；恢复环境后运行 `hdsh pairing merge --resolve`，或执行 `git merge --abort`。

prek 钩子在 [prek.toml](../prek.toml) 中配置为快速本地检查点：

- `pre-commit` 对照暂存的所属文件字节校验暂存的配对记录，以及配置列出的其余暂存检查。
- 钩子有意不运行测试、类型检查或全语料配对检查。贡献者只运行[与改动行为相关的检查](../AGENTS.md#run-relevant-checks-locally)一次；穷尽矩阵归 CI。

### CI 门禁

无凭据的 [CI 工作流](../.github/workflows/ci.yml)运行带覆盖率门禁的测试套件、lint、两个类型检查器，以及整树运行的全部文档门禁。Issue 与 PR 策略在各自的工作流中对配置的 GitHub Projects 运行。当前作业清单见工作流文件。

### 日常命令

根[贡献者说明](../AGENTS.md#commands)汇总常用命令；`uv run hdsh --help` 与 `uv run hdsh <domain> --help` 以逐级递进的帮助暴露完整命令树。选择覆盖改动面的最小检查。文档变更重新记录被编辑的配对；包公开行为的变更还要更新所属文档。

### TODO 标记

在代码中用三种注释标记之一按紧急度标记已知问题——`FIXME` 阻塞发布、`TODO` 尽快处理、`XXX` 将来再说。
