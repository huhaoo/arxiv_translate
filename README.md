# arxiv-translate

## Stable Baseline

The active stable baseline is `72fd7d8c2415733f6ee914340bf7e2e1a711227a`.
The superseded experimental translation protocol is preserved as
`cdd2533d506d5f943a453274af0a7968ad7e8d93` and tagged
`pre-stable-rollback-cdd2533` for future comparison or recovery.

用于将 arXiv TeX 源码翻译为中文、重新编译论文，并支持一键导入 EndNote 的命令行工具。

支持的 CLI 输入形式：

- `https://arxiv.org/abs/2401.00001`
- `https://arxiv.org/pdf/2401.00001`
- `https://arxiv.org/html/2401.00001`
- 只输入 arXiv ID，例如 `2401.00001`
- 旧版 ID，例如 `hep-th/9901001` 或 `https://arxiv.org/abs/hep-th/9901001`

## 环境要求

- Python 3.10+
- 一个兼容 DeepSeek 的 API key
- 本地 TeX 发行版，用于编译；建议安装 `latexmk` 和 `xelatex`

翻译器会使用 `config.local.jsonc` 中配置的单个 OpenAI 兼容 chat completions 接口。该文件必须是一个 JSONC 对象，并包含下方示例中的所有字段。JSONC 支持 `//` 和 `/* ... */` 注释，VSCode 会按原生格式识别，不会把注释标红。

## API key 配置

将 `config.local.example.jsonc` 复制为 `config.local.jsonc`，然后把你的 API key 填进去：

```jsonc
{
  // DeepSeek API key
  "deepseek_api_key": "sk-your-deepseek-api-key",
  "deepseek_model": "deepseek-v4-pro",
  "deepseek_appendix_model": "deepseek-v4-flash",
  "deepseek_base_url": "https://api.deepseek.com/chat/completions",
  "use_proxy": true,
}
```

`use_proxy` 默认为 `true`，使用系统环境中的 HTTP/HTTPS 代理。设为
`false` 时，arXiv 元数据、BibTeX、PDF、源文件和 DeepSeek 请求都会绕过代理。

两个模型字段共用同一个 API key 和接口地址，分别用于正文和附录翻译。请求失败时会按单个客户端的重试策略重试，不再切换到其他 API 配置。

`config.local.jsonc` 已被 git 忽略，因此 key 只会保存在你的本机。

## 使用方法

```powershell
python -m arxiv_translate https://arxiv.org/abs/2401.00001
```

不传入链接时会进入交互模式。每输入一行，都会对一篇论文执行完整工作流：

```powershell
python -m arxiv_translate
arxiv> https://arxiv.org/abs/2401.00001
arxiv> 2402.00002
arxiv> exit
```

在 Windows 上，也可以在项目文件夹中双击 `arxiv_translate_interactive.cmd`，打开同样的交互模式。启动器会转发选项，因此 `arxiv_translate_interactive.cmd --redo` 会以强制重跑模式打开交互模式。在这个 Windows 交互控制台中，按上/下方向键可以召回历史输入，历史记录会保存在本地的 `.arxiv_translate_history`。

在 Linux 或 macOS 上，可以使用 bash 启动器：

```bash
chmod +x arxiv_translate_interactive.sh
./arxiv_translate_interactive.sh --redo
```

不传参数时会进入交互模式；传入 URL、arXiv ID 或其他 CLI 选项时，会原样转发给 `python -m arxiv_translate`。

常用选项：

```powershell
python -m arxiv_translate https://arxiv.org/pdf/2401.00001.pdf --no-compile
python -m arxiv_translate 2401.00001 --main paper.tex
python -m arxiv_translate 2401.00001 --chunk-chars 2048 --context-chars 250 --parallel-chunks 8
python -m arxiv_translate 2401.00001 --redo
python -m arxiv_translate 2401.00001 --superscript-citations
python -m arxiv_translate https://arxiv.org/html/2401.00001 --keep-source-archive
```

如果输出目录中已经有完成结果，命令会在发起网络请求或 DeepSeek 请求前跳过这篇论文。使用 `--redo` 可以强制重新执行完整工作流。

默认保留论文原有的引用命令和引用样式，不合并或改写引用。需要紧凑的数字上标引用时，使用 `--superscript-citations`；也可以使用别名 `--lightcite` 或短选项 `-S`。

默认情况下，每次翻译请求会发送最多 2048 个字符的 TeX 分块，并附带前后各 250 个字符的上下文。提示词会要求 DeepSeek 只把上下文用于术语和连贯性，并且只输出当前分块的译文，不重复上下文内容。

默认最多并发发送 8 个翻译分块。若需要严格顺序请求，可以使用 `--parallel-chunks 1`；如果 API 速率限制较紧，也可以调低该值。

如果 DeepSeek 返回 markdown 代码围栏或内部提示边界标签，而不是原始 LaTeX，翻译请求会立刻重试；默认重试上限是 3 次。

翻译保护规则、编译后的自动处理、PDF 元数据和 EndNote 附件规则见
[翻译与编译行为](docs/translation-behavior.md)。

`prompt` 和 `case` 是两个例外：它们通常由源码定义为 `tcolorbox` 的
listing 环境，内部可能包含 `#` 标题、`{变量}` 占位符、命令或结构化的
模型输入/输出。因此工具会保留这两个环境（包括标题和内部内容）原样，不将其
发送给翻译模型。这只影响名称恰为 `prompt` 或 `case` 的环境，不影响普通正文
或其他文本框；相应地，框内面向读者的英文说明也会保持英文。

附录 TeX 文件，以及 `\appendix` 命令之后的分块，会使用 `deepseek_appendix_model`，这样较长的附录可以使用成本更低的 flash 模型，而正文仍使用 `deepseek_model`。

翻译过程中，命令会打印紧凑的分块进度条，让长论文也能看到明确的推进状态。

分块只会在段落边界切分。如果单个段落长度超过分块大小，会保持该段落完整，不会在段落中间切开。

在分块翻译之前，工具会结合 arXiv 元数据和本地 TeX 源码生成 `paper-guide.md`，不会为 guide 发起额外 API 请求。模板在元数据存在时收录 arXiv 标题、摘要、主分类和全部分类；缺失的元数据栏目会直接省略。它还包含章节结构、源码文件、文档类、宏包、环境、风格规则、LaTeX 注意事项、固定译法、保留英文词，以及从源码确定性提取的预定义命令。后续翻译请求会在动态上下文前附加这份固定指南，以提高术语一致性和缓存命中率。
默认保留英文的术语维护在 `arxiv_translate/terminology/preserved_terms.md`，例如 `token`、`scaling law`。如果你希望某些术语始终不要翻译，直接把它们按同样格式追加到这个文件里即可。
默认优先采用的中文术语维护在 `arxiv_translate/terminology/preferred_translations.md`。如果你希望某些术语始终翻译成固定中文，例如把 `mechanistic interpretability` 统一翻成“机制可解释性”，直接把它们追加到这个表里即可。

输出结构：

```text
arxiv_outputs/
  2401.00001/
    original.pdf         # arXiv 原始 PDF
    endnote.enw          # 带元数据和附件的 EndNote Import 文件
    paper-guide.md       # 缓存的整篇论文翻译指南
    source/              # 解压后的原始源码
    translated/          # 翻译后的 TeX 目录树，编译后包含 translate.pdf
      compile.log        # 执行编译时的 LaTeX 编译器输出
    source-download.bin  # 使用 --keep-source-archive 时可选保留
    translation-cache.json
```

使用 `--output-dir runs` 可以改为保存到 `runs/{arxiv-id}/` 下。

如果 arXiv 没有提供这篇论文的 TeX 源码，命令仍会写入 `original.pdf` 和 `endnote.enw`，但会跳过翻译和编译。

要把记录添加到 EndNote，请使用 `EndNote Import` 过滤器导入 `endnote.enw`。该文件包含 arXiv 元数据，以及 `original.pdf` 的文件附件条目；它的标签是 arXiv 导出的 BibTeX 引用中的 key。当 TeX 翻译和编译成功时，它也会包含翻译后的 PDF。

## 验证

```powershell
python -m arxiv_translate --help
python -m compileall arxiv_translate
```
