# RFC: 以 composite action 分发议题策略 workflow

Status: implemented

[English](2026-09-17-issue-policy-composite-actions.md) | 中文

## 问题

策略引擎随包分发：`hdsh policy pr` 与 `hdsh policy lifecycle` 是普通 CLI（命令行界面）命令，哪里都能装。workflow 胶水却不可分发。flavor 解析、凭据校验、受信的 default branch checkout、引擎供给、钉住 SHA 的第三方 action——全部只存在于本仓库自己的 `issue-policy.yml`（78 行）与 `issue-lifecycle.yml`（107 行）里。想要同等 Issue/PR 治理的消费方仓库只能整文件复制；复制品与上游漂移，每次上游改进都要在每个消费方手工重新对 diff。接入故事止步于钩子 manifest（元数据清单）：prek 分发了门禁，没有人分发 workflow。

## 决策

### 两个 composite action 持有全部胶水

`issue-policy` 与 `issue-lifecycle` 是 `.github/actions/<name>/action.yml` 下的 composite action——GitHub 官方教程为仓库内 action 推荐的位置。每个 action 承载此前 workflow 文件承载的一切：从消费方仓库的策略配置解析 flavor、按 flavor 校验凭据、经钉住 SHA 的 `actions/create-github-app-token` 嵌套 `uses:` 铸造 GitHub App 令牌、受信 checkout、引擎供给、CLI 调用。GitHub 的事件触发器无法跨仓库订阅，消费方的 workflow 文件永远保留——但它缩减为触发器集合、最小 `permissions` 块、一行带凭据 inputs 的 `uses:`。这取代 [github-workflow RFC（决策记录）](../process/2026-09-07-github-workflow.zh.md)决定的胶水归属，后者已在同一变更中更新；其不变量存续——策略逻辑留在引擎，workflow 文件只订阅与调用。flavor 逻辑位于各 action 目录内的 `scripts/flavor.py`，两个 action 逐字节相同，因此 CI 彩排可以直接执行它。

### 凭据经 inputs 进入；action 从不触碰 secrets

平台禁止 composite action 内部使用 `secrets` context，调用方因此把 secrets 映射为按角色命名的 inputs：`github-token`（默认 `${{ github.token }}`，在调用方一侧求值）、`project-token`、`app-client-id`、`app-private-key`。action 依据配置的 `accountType` 校验 inputs 完整性，按 flavor 显性失败——与此前 workflow 脚本执行的凭据矩阵相同。App 令牌在 action 内部铸造，组织与 user 两种 flavor 对调用方都只剩一步，与[身份模型](../feature/2026-09-08-user-account-issue-policy.zh.md)一致。本仓库的密钥族系随采纳 action 的 workflow 翻转对齐：`HDSH_PROJECT_PAT` 更名 `HDSH_ISSUE_PROJECT_TOKEN`，并入 `HDSH_ISSUE_APP_CLIENT_ID` 与 `HDSH_ISSUE_APP_PRIVATE_KEY`——一个前缀、按角色命名的名字，陈述凭据通往何处，而非它如何铸造。

### 策略配置保持为仓库内文件

`config.json` 仍是策略的唯一归属；action 只接收一个 `config-path` input，默认 `.github/issue-management/config.json`。策略语义不搬进 action inputs 或仓库 variables：`pull_request` 事件从 PR 的 merge ref 读取 workflow 文件，嵌在其中的 input 值受 PR 控制，PR 就能放宽校验自己的策略；仓库 variables 的变更不经评审。复杂且由评审治理的配置属于仓库文件——release-please、semantic-release、dependabot 的先例。引擎把配置中的 `owner`、`repository`、`accountType` 与事件载荷的 repository 上下文交叉验证（`hdsh.policy.commands.validate_context`），不符即显性失败（fail-loud），在任何 API 调用之前捕获改名的仓库与复制粘贴来的配置。

### 受信来源：default branch 上的 config，钉住的引擎

action 从 default branch checkout 消费方的配置，绝不用 PR head——保持防自我修改性质。引擎来自必填的 `hdsh-ref` input——一个 git ref（tag 或完整 SHA）——以 `uv tool run --from "harness-deepseek-harness @ git+<clone-url>@<hdsh-ref>"` 供给；clone URL 取自事件载荷，同一个 action 因此服务任何 fork 或镜像。治理引擎永不漂浮在 `latest` 上。把供给方式换成 PyPI 钉住（`==<version>`）是留给发布那一天的后续事项。

### 本仓库以全限定引用自持，绝不用相对路径

本仓库自己的 workflow 以同样方式调用；翻转作为紧随其后的变更落地，因为 default branch 必须先承载 action，任何调用方才能钉住它。相对引用 `./.github/actions/...` 会从 PR 的 merge ref 加载 action，等于允许 PR 修改自己的校验器。default branch 引用精确保持原有信任语义：胶水与引擎永远来自经过评审的 default branch 状态，胶水变更只能经评审落地。把自引用不可变地钉在 release tag 上是更严的纪律，本记录刻意不采纳：它会在两次发布之间冻结校验器，给每次发版加一步 pin 升级，却不改变攻击者可达的任何东西。

## 验证

`tests/policy/` 钉住每一种交叉验证错配：缺失 repository 上下文、缺失 owner 上下文、repository、owner、accountType 矛盾，以及 CLI 的诊断路径。CI 的 `action-rehearsal` job 对 user 与 organization 两类 fixture 执行两个 action 的 `flavor.py`（快乐路径加两条显性失败路径），以引擎的准确 CLI 调用方式运行一份与事件载荷矛盾的配置；自 workflow 翻转变更起，它还断言两个自托管 workflow 引用均为全限定、任何地方都没有相对 `uses:`。在真实 API 流量下对真实消费方仓库的彩排留作未来工作，直到存在 release tag。

## 备选方案

**可复用 workflow。** 调用方更薄、原生支持 `secrets: inherit`，但调用方仍是与事件订阅耦合的完整 workflow 文件；lifecycle workflow 精心调过的步骤级跳过（良性评审事件上绿色 check 而非灰色 skipped）迁入被调用 workflow 的 job 语义时处处别扭；升级也不再镜像消费方已经遵循的 prek `rev:` 钉住模型。

**生成 workflow 加漂移门禁。** 一个命令把完整 workflow 文件写进消费方，一道门禁对照上游比较它们。复制语义原样保留——每次改进都会分叉每个消费方直到重新生成；而解决方案在 composite action 只有一个活动部件的地方长出第二个。

**策略配置作为 action inputs 或仓库 variables。** 因信任否决：`pull_request` 事件从 PR merge ref 读 workflow 文件，PR 可以放宽校验自己的策略；仓库 variables 不经评审即可变更；且文件仍是 CLI 在 Actions 之外读取的唯一入口。

## 后果

- 消费方移动一个 `uses:` ref 即升级 workflow，与 prek 钉住模型同构；凭据面保持显式且最小——四个按角色命名的 inputs 加两个路径。
- composite action 不能直接读 `secrets`——每个凭据都必须以 input 呈现，调用方映射错误会在 flavor 步骤显性失败，而不是悄悄地以「无身份」通过认证。
- 以 default branch 自持意味着本仓库用 main 的胶水校验 main——与此前语义相同，但胶水回归在合并即刻影响校验，而不是等到下一次发布边界。
- 组织/user 凭据矩阵让 action 的测试面翻倍；彩排 job 承载本地的一半，lifecycle action 在新结构下保住了「绿而非灰」的步骤门控。
- 经 git ref 供给引擎在 PyPI 存在前即可工作，但每次 run 都要重新解析仓库；PyPI 钉住的切换排在首次发布之后。
