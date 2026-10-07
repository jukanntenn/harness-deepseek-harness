# RFC: 由仓库 config 拥有的 pull-request head-ref 豁免

Status: implemented

[English](2026-10-07-pull-request-head-ref-exemptions.md) | 中文

## 问题

pull-request 政策把每笔非草稿、真人作者的 pull request 绑定到引用、`kind/*` 与 `area/*` 规则上。整类 pull request 天然无法满足引用规则：发布 PR 滚动版本号与变更日志，没有可解决的同仓库 Issue，于是每次运行都倒在 `PR body must reference at least one same-repository Issue` 上。第五个接入方带着本地 MRFC（2026-08-24）在本地打补丁，并报告在上游给出机制之前每次发版都要维护者手工放行。把 `release/**` 豁免硬编码进上游则是把随部署而异的选项烤进门禁——正是仓库配置规约所禁止的 tunable 形态。

## 决策

- `config.json` 新增 `pullRequestExemptHeadRefs`：pull-request head ref 名的非空 `fnmatch` glob 列表，载入即校验——非字符串列表、含空串或非字符串项都以字段名显性失败。缺省或为空即无豁免，这是每个仓库起步时的封闭集合行为；该字段是[配置所有权 RFC](2026-10-01-consumer-configuration-ownership.zh.md) 下的消费方自有配置。
- glob 采用 `fnmatch` 语义、按 ref 名大小写敏感比较：`*` 可跨 `/`，因此一条 `release/*` 覆盖嵌套的发布 ref，`release/**` 与 `release/*` 等价。
- pull-request 快照携带 head ref，`hdsh policy pr` 在校验之前先查豁免：命中的 pull request 打印一行点名该 ref 并绿色退出——与既有的「草稿与自动化不在范围」路径同构。
- 豁免是整政策级的：命中的 pull request 同时跳过引用、`kind/*` 与 `area/*` 规则。生命周期流程不受影响——没有引用的发布 PR 本就无所转移。

## 考虑过的替代方案

**上游硬编码 `release/**` 豁免。** 否决：哪些 head 豁免因仓库而异；门禁常量恰是配置规约要消灭的硬编码 tunable。

**只豁免引用规则。** 否决：把一个适用性决定拆成两个配置面，而发布 PR 同样不带 `kind/*` 与 `area/*`——没有接入方要求这个拆分。

**按 pull-request 标签豁免。** 否决：作者可自贴的标签让任何作者自我豁免；head ref 可由分支规则保护，且本就承载发布身份。

**从仓库 variables 读取模式。** 否决：`config.json` 是经过校验、与事件交叉核对的配置之家，workflow 本就从受信默认分支状态读取它；第二来源只会与之漂移。

## 后果

换来的是：发布类 pull request 带一行解释绿色落地，消费仓库以受评审的配置拥有自己的豁免列表，无该字段的仓库行为分毫未变。

付出的是：多一个受校验的配置面，且过宽的 glob 会静默豁免每笔命中的 pull request——运行日志里的豁免行是可见痕迹，配置文件与代码同等受评审。

## 验证

单元测试钉死 glob 语义（全等命中、`*` 跨 `/`、大小写敏感、空模式集永不命中）、载入校验（缺省默认为空；非列表、空串项、非字符串项各自以字段名显性失败）与 client 路径（命中的 head ref 打印豁免行且无 `::error` 注记；快照携带 head ref）。默认配置——无该字段——运行不变的政策，由既有 pull-request 套件钉住。
