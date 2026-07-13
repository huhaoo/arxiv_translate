# 翻译与编译行为

本文说明翻译器为保证 LaTeX 可编译性而采取的保护和自动处理规则。

## 不发送给翻译模型的内容

### 宏定义文件

工具会跳过以 `macro`、`macros`、`command`、`commands` 或 `preamble`
命名的宏定义文件；没有 `\begin{document}` 且包含大量宏定义的辅助文件也会跳过。
例如，`\newcommand{\taskstate}{...}`、`\newenvironment{...}` 和
`\newtcblisting{...}` 之类的定义会原样保留，避免模型修改命令名、参数或花括号，
从而导致正文中出现未定义命令。

这项规则以可编译性为优先：若一个上述命名的文件同时含有可见正文，其正文也会
保留英文。包含 `\begin{document}` 的主文档不会因少量宏定义而被整体跳过。

### `prompt` 与 `case` 环境

名称恰为 `prompt` 或 `case` 的环境会整体保留，包括可选标题和内部内容。它们常由
`tcolorbox` 定义为 listing，内部可能有 Markdown 的 `#`、`{变量}` 占位符、模型
输入/输出、程序命令或结构化示例；这些内容被常规文本翻译改写后，可能改变提示词
含义或无法编译。

这不是对所有文本框的通用规则，普通 `tcolorbox` 和正文仍会翻译。相应地，
`prompt`、`case` 框内面向读者的英文说明目前也会保留英文。

## 翻译后的自动处理

- 清理 `\caption{...}` 参数内的空段落：将连续空行收敛为空格，避免 `caption`
  宏在参数中遇到段落标记而报错。
- 为中文 XeLaTeX 编译应用兼容性处理；对于 `acmart` 文档，会同步其行距快照，避免
  `ctex` 改变行距后触发类文件的错误检查。
- 保持论文的可见标题为原始英文标题，并在 PDF 元数据标题加入
  `[arXiv:<编号>]`。该元数据设置放在 `\maketitle` 后，以覆盖可能由文档类重置的
  标题信息。

## 产物与 EndNote

成功编译后，最终译文 PDF 会统一命名为
`arxiv_outputs/<arXiv ID>/translated/translate.pdf`。`endnote.enw` 会包含 arXiv
元数据，并附加原始 `original.pdf` 与成功生成的 `translate.pdf`。没有 TeX 源码或
编译未成功时，则只保留可用的原始 PDF 附件。
