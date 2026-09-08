# RFC: basedpyright 警告面：类型化替身与仅限 tests 的私有访问豁免

Status: implemented

[English](2026-09-08-basedpyright-warning-surface.md) | 中文

## 问题

类型门禁（pre-push 钩子与 CI 中的 `uv run basedpyright`）以 `typeCheckingMode = "all"` 运行，报告了 251 条 diagnostic——全部位于 `tests/`，`src/` 中一条也没有。每条都是 `warning` 级别，因为 tests execution environment 把十二条规则降级为 `"warning"`，默认 warning 是咨询性的；但 basedpyright 的 `"all"` 模式默认启用 `failOnWarnings`，每条 warning 照样让 CLI 失败。降级因此毫无作用，本仓库在第一次 push 时就无法通过自己的类型门禁，而本意的策略——对 `src/` 严格、对刻意为之的 test double 宽容——只是一句无法验证的假设。两个更深的事实藏在下面：basedpyright 完全不认 `# type: ignore` 注释，所以测试套件里唯一一处压制是死文本；降级清单也悄悄越出了白盒私有访问，扩到十二条互不相关的规则，把测试完全付得起代价的信号一并丢弃，`reportArgumentType` 就在其中。

## 决策

门禁保持严格；噪音被修掉，而不是放宽掉。`failOnWarnings = true` 在配置中显式声明，无论 basedpyright 未来默认值如何变化，任何 error 或 warning 都会让 pre-push 与 CI 中的 `basedpyright` 失败。tests execution environment 只豁免两条规则：`reportPrivateUsage` 与 `reportPrivateLocalImportUsage`（`"none"`）。测试以白盒方式行使私有契约、直接 patch 模块内部——这与 ruff 对 `tests/**` 的 per-file ignore 用 `SLF001` 和 `ARG` 已编码的立场一致——豁免范围只限这两条规则、只限 `tests/`。其余所有 diagnostic 在任何地方都保持严格默认，`src/` 环境原封不动。

清零 warning 的过程把测试套件带到了门禁本已宣称的标准。140 条 `reportUnknownLambdaType` 来自 stub lambda，而 Python 语法不允许 lambda 参数带注解；它们现在是镜像被替换函数真实签名的类型化 def，重复的固定结果 `subprocess.run` 替身则共用 `tests/helpers.py` 里一个泛型 `completed_run` helper。未使用的捕获被删除或加下划线前缀，test double 的类属性补上注解，一个死掉的嵌套 helper 被删除，唯一一处对基类的鸭子类型委托用 `# pyright: ignore[reportArgumentType]` 加 `# ty: ignore[invalid-argument-type]` 压制——pyright 形式的注释是 basedpyright 唯一认的一种。

## 验证

`uv run basedpyright` 报告 0 error、0 warning，退出码 0。`uv run pytest` 在 100% 分支覆盖率门禁下通过 991 个测试且行为无变化，`uv run ruff check .` 与 `uv run ruff format --check .` 保持干净。`uv run ty check` 通过且无变化。

## 备选方案

**`failOnWarnings = false`（warning 在全局变为咨询性）。** 这个开关是全局唯一的——execution environment 只能覆盖规则级别，不能覆盖退出行为——`src/` 的 warning 也将不再阻塞，未来的真实缺陷可能以 warning 身份合入。放宽必须让错误面最小，所以方向反过来：修掉套件噪音，只在一个环境里豁免一个规则族。

**在门禁命令中加 `--level error`。** 同样是过宽的放宽，而且它把 warning 从输出中完全藏掉，连咨询可见性都失去了。

**保留十二条 `"warning"` 降级。** 它们编码的是「warning 是咨询性的」这一假设，而 `"all"` 模式的 `failOnWarnings` 否定了它；在阻塞式门禁下每条降级照样失败，配置记录的是一项并不存在的策略。被降级的多数规则——未使用变量、未注解属性、未知 lambda 类型——在测试里只需花类型标注的功夫就能满足，降级丢掉的是套件付得起代价的信号。

**basedpyright 的 baseline 功能。** 把 251 条 diagnostic 收进 baseline 是把噪音冻结而不是清除，diagnostic 减少时它还会自动更新（同一次运行里掩盖回归），并给评审添一件会移动的工件。套件规模小到可以直接修掉。

**把测试要用的私有名字导出。** 为了满足测试而加宽 `src/` 导出是把所有权倒置：私有契约正是被测对象。带范围限定的豁免记录的才是这一立场。

**逐处用 ignore 注释压制。** `# type: ignore` 在 basedpyright 下是惰性文本，逐处压制意味着在每个替身里撒 `# pyright: ignore`；类型化签名记录了每个替身的契约，让唯一不可避免的那处压制保持为例外。

## 影响

- `basedpyright` 对 `src/` 与 `tests/` 的任何 error 或 warning 一视同仁地阻塞；唯一的沉默是 `tests/` 下那两条私有访问规则。新 warning 直接出现在作者的 pre-push 钩子里，没有 baseline 文件要更新，也没有阈值可谈判。
- test double 必须保持完整类型化签名。这与 ruff 现有的 `ARG` per-file ignore——fake transport 与协议替身必须保留完整签名——一致，并把那条惯例升级为类型检查的硬要求；`completed_run` 是固定结果 `subprocess.run` 替身的共享形态。
- 本仓库的压制使用 `# pyright: ignore[rule]`，辅以面向第二检查器的 `# ty: ignore[code]`；`# type: ignore` 注释在 basedpyright 下是惰性的，不得依赖。
- tests environment 的配置从十二条降级缩到两条豁免，配置从此说出真实策略：白盒私有访问是有意的，其余一切按严格默认执行。
