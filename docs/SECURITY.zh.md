# 安全策略

[English](SECURITY.md) | 中文

## 如何报告漏洞

使用 GitHub 的私密漏洞报告：打开仓库的 **Security** 标签页，选择 **Report a vulnerability**。报告会开启一个只有维护者可见的私密 advisory 草稿。绝不开公开 issue，也绝不在公开场合讨论未修复的漏洞。

## 报告应包含

- 受影响的门禁或命令（例如 `hdsh pairing verify`、`hdsh policy lifecycle`）。
- 复现：配置文件、最小载荷，以及环境（操作系统、Python、prek 与 uv 版本）。
- 你评估的影响——攻击者能得到什么，例如执行命令、获取 token、污染配对记录。

## 响应预期

尽力而为的单一维护者：7 天内确认收到；修复时限随严重度而定；协调披露——修复随一份已发布的 GitHub Security Advisory（可分配 CVE）一起交付，并经 Dependabot 传导给下游使用方。报告者会在 advisory 中获得署名致谢。

## 范围与信任边界

策略引擎在 GitHub Actions 内处理 issue 与 PR 的标题、正文和标签，同时持有 `GITHUB_TOKEN` 和一枚项目范围的 token：这些内容是**不可信输入**，引擎只将其当作数据——构造的内容若在这些 workflow 中导致命令执行或 token 外泄，属安全漏洞，在范围内。门禁在使用方仓库内运行时，读取的是使用方自己的文件作为配置；那些文件属于使用方的信任域，不在本项目的威胁模型内。秘密只以仓库 CI secrets 的形式存在，引擎从不回显 token 值。

## 支持版本

| 版本 | 支持 |
|---|---|
| main 分支 | ✅ 尽力而为 |

尚未发布任何版本，`main` 是唯一支持面；首个版本打 tag 后，版本行会出现在这里。
