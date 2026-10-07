# RFC: 策略门禁只跳过引入或替换 config 的那一笔 pull request

Status: implemented

[English](2026-10-05-first-adoption-policy-bootstrap.md) | 中文

## 问题

两个策略 workflow 都检出仓库默认分支并在那里读取 `.github/issue-management/config.json`——这是防止 pull request 篡改自身校验器的防篡改设计，记录于 [GitHub workflow RFC](../process/2026-09-07-github-workflow.zh.md)。于是首笔接入 PR 用自己的校验器对着一个没有 config 的默认分支运行：合并之前，两个 workflow 的每次运行都以文件缺失错误失败，迫使维护者带红合并——第四个接入方报告的引导悖论。没有任何文档预告过这个预期中的红，它到来时读起来就像所接入门禁自身的缺陷。

那次修复把跳过条件只系于 config 的缺失，于是第五个接入方的替换型接入——默认分支上已有一份旧 schema 的 config.json，是合法 JSON 却没有 `accountType`——根本走不到跳过分支：flavor 解析读到外来文件，死在 `unknown accountType 'None'` 上，成为阻塞合并的唯一必需红检查。默认分支在该路径上已有任意前代 config 的消费方是正当的接入场景，不是边角案例。

## 决策

- flavor 解析步骤把「默认分支没有可用的策略 config」——config 缺失、JSON 不可解析、或没有合法的 `accountType`——精确分为两种情形。当事件的 pull request 新增或修改了该配置路径——经 REST pull-request 文件列表核验、跟随分页——本次运行发出一条 `::notice` 与一个门控后续凭据铸造和校验步骤的 `skip=true` 步骤输出：在那笔 pull request 合并之前没有可执行的政策，而唯一从不读取自身副本的那笔 pull request，恰是无法经此路线篡改校验器的那次运行。替换型接入与首次接入走同一条分支。
- 其余一切不可用的 config 都点名其不可用状态、作为漂移显性失败：无可用 config 仓库上的 issue 事件、无关的 pull request、接入之后被删除的 config、被损坏到无法解析的 config。这个显性分支同时是「退接入」探测器——政策配置消失或不再是 hdsh 策略的仓库保持红，而不是悄悄通过。
- 引入检查运行在 composite action 的 flavor 脚本内部，消费方移动一个 `uses:` ref 即完成升级；消费方安装的薄 workflow 模板无需改动，本仓库自己的两个内联 workflow 携带相同分支。文件 API 不可达或不可读时显性失败，而不是猜测 pull request 的内容。
- 接入手册写明该行为：接入 PR 是已知的引导时刻，不需要带红合并。

## 验证

封闭脚本测试对着本地分页文件 API 驱动两个 flavor 脚本：引入 config 的 pull request 带 notice 与 `skip=true` 输出跳过；替换型接入——默认分支上的外来 schema 或不可解析的 config——只对改写它的那笔 pull request 跳过，其余情形显性失败；无关 pull request、无 pull request 上下文的事件、缺失的令牌映射、失败的 API 各自保持显性失败；既有 config 的 flavor 解析不变。actionlint 通过改动后的 workflow 与 action。

## 考虑过的替代方案

**把所有 config 缺失降级为 warning。** 否决：一笔删除 config 的 PR 合并之后，workflow 将永远跳过——一个检查全绿却已静默退接入的仓库。只有引入或替换 config 的那笔 pull request 可以跳过。

**跳过任何触及 config 的 pull request。** 否决：只要默认分支持有可用的策略，编辑 config 的 pull request 就是一次普通的政策变更，仍要对着受信的默认分支状态受校验；跳过只适用于「没有可校验的政策」的情形。

**从 PR 头部读取 config。** 否决：重新打开了默认分支检出所要关闭的「自我校验」漏洞。

**把这个红写进文档、带红合并。** 否决其作为完整修复：它有效一次，但每个未来消费方对门禁的初次体验都是维护者必须有意覆盖的假失败，手册得以永久传授这个覆盖动作。

## 后果

换来的是：接入 PR——无论引入 config 还是替换外来 config——带一条解释性 notice 绿色落地，精确的跳过条件保住了防篡改性质——校验器仍只读取受信的默认分支状态——同时让静默退接入变得响亮。

付出的是：flavor 步骤仅在引导路径上执行一次带鉴权的 API 读取，其失败是显性的；停留在旧 action ref 上的消费方在以新 ref 重跑 `hdsh adopt apply` 之前保持旧行为，而这本就是常规升级路径。
