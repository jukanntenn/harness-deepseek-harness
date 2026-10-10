# RFC: 让被接入的门禁对行尾稳定，并可在 Windows 上运行

Status: implemented

[English](2026-10-08-windows-adoption-platform-fixes.md) | 中文

## 问题

第一个 Windows 接入方报告了三个阻断两条部署路径的平台缺陷，以及同一报告带出的三个接入体验缺陷。其一，`zoneinfo` 在 Windows 上没有时区数据库，于是 `hdsh adopt plan --time-zone Asia/Shanghai` 拒绝了合法的 IANA 时区——被拒的正是诊断文本自己举的例子——而只安装已声明依赖的 prek 钩子环境在加载 `config.json` 时以 `ZoneInfoNotFoundError` 崩溃。其二，工具自有的文本写盘全部走 `Path.write_text`，其文本模式把 `\n` 翻译为平台行尾：Windows 上 record 命令写出 CRLF sidecar，而门禁自己的解析器拒绝它，apply 之后每一对已安装配对立即读作「malformed／out-of-sync」。其三，配对记录哈希原始工作区字节，于是在 `core.autocrlf` 之下同一文件在工具链调用间于 CRLF 与 LF 之间翻转，内容零变化而门禁间歇性变红；报告方最终靠钉住 `eol=lf` 并全语料归一才稳定下来。体验缺陷：`gh auth status` 的 scopes 行带有 `- ` 列表前缀，缺 `project` scope 的提示从未触发，令牌缺 scope 时 preflight 仍报「ready」；推导阻塞把 wizard 的消息打印两遍——一遍作 reason、一遍作 suggestion；apply 为既存的消费方文档安装模板默认词数预算，让 budgets 门禁在 apply 当天就对从未由接入写下的内容变红。

## 决策

- `tzdata` 成为 `sys_platform == 'win32'` 依赖：它是 `zoneinfo` 在 Windows 上唯一的 IANA 来源，时区校验、策略配置加载与接入日期因此在该平台可用；Linux 与 macOS 继续读系统数据库，解析行为不变。
- 工具自有的文本写盘一律落确切字节（`write_bytes`）：配对 sidecar、adopt manifest、brief 的对侧结果、RFC 封存 manifest。记录 sidecar 恒为 LF 行尾，两种行尾都可解析，被 smudge 的检出仍可读。
- 配对记录哈希并存储每一侧行尾规范化后的字节——CRLF 折叠为 LF，即 clean-filter 视图。worktree 与 index 两平面哈希一致，任何工具的行尾翻转都不能把已确认的配对推出同步；在以 LF 提交的目录树上规范化形态就是文件本身，既有记录保持有效。合并组合存储规范化 blob，并按规范化形态比较暂存与工作区内容；仅行尾差异不再是「未暂存内容」，而真正不同的暂存合并仍被拒绝。用旧版 hdsh 记录过原始 CRLF 字节的消费方需重录一次。
- gh scope 解析器接受两种披露形态——裸 `Token scopes: ` 行与 gh 带 `- ` 前缀的列表行——对任何不认识的形态保持沉默。
- 推导失败的阻塞只把 wizard 消息打印一遍，作为建议解决方式；reason 固定为「could not be derived」。
- apply 对判定为消费方所有的模板配对不安装其 `docBudgets` 条目；plan 输出点名被去掉的目标，让消费方知道日后自行设置上限。

## 验证

单元测试钉住容忍 CRLF 的记录解析；record 命令对 CRLF 内容写出仅含 LF 的 sidecar 并验证为绿；记录后的行尾翻转在 worktree 与 index 两平面保持为绿，而 CRLF 之下的真实内容漂移仍然变红；合并解析器容忍仅行尾的工作区翻转，却仍拒绝被偏移的暂存字节；带列表前缀的 scopes 行获得刷新提示，带 `project` 的前缀行保持沉默；推导阻塞的诊断恰好打印 wizard 消息一遍；带既存长文档的 apply 安装不含其预算条目的 docs manifest 并输出点名注记。镜像字节一致、配对、docs 与 RFC 各门禁在 Linux 上重跑为绿。

## 考虑过的替代方案

**要求消费方为语料钉住 `eol=lf`。** 否决作为机制：它把门禁正确性押在每个消费方都正确编辑 `.gitattributes` 上，而 adopt 有意不接管仓库的 eol 策略。规范化哈希让门禁在每个平台都对检出配置无感；钉行尾仍是可选的消费方卫生习惯。

**经子进程哈希 git clean-filter 的输出。** 否决：每次检查每个文件都要起一个 git 进程，而实际会发生的情形下返回的字节与把 CRLF 折叠为 LF 完全相同；孤立 `\r` 或二进制内容根本进不了配对记录。

**用 `newline="\n"` 而非 `write_bytes` 写盘。** 纸面等价，形式上否决：`write_bytes` 是全称的——不存在未来写盘者可能忘带该参数的文本模式调用点。

**从注册表推导 Windows 时区。** 否决：`--time-zone` 旗标已经存在，推导面保持每类平台一种机制，阻塞诊断本已点名解法；ADOPT.md 现在写明 Windows 显式传该旗标。

## 后果

换来的是：Windows 接入端到端可用——plan 校验时区、钩子环境加载策略配置、已记录配对在每个平台的检出配置之下保持绿灯，preflight 提示、阻塞诊断与 apply 日的预算都按文档行为。代价是：用旧版 hdsh 记录过原始 CRLF 字节的消费方需对每个受影响配对重录一次；对已配对文件仅改行尾的编辑不再被配对门禁当作漂移——这是设计使然，wrap 门禁与评审仍然看得见文件本身。
