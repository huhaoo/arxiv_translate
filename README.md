# arxiv-translate

Command line tool for translating arXiv TeX sources into Chinese and rebuilding the paper.

Supported input URL forms:

- `https://arxiv.org/abs/2401.00001`
- `https://arxiv.org/pdf/2401.00001`
- `https://arxiv.org/html/2401.00001`
- old-style IDs such as `https://arxiv.org/abs/hep-th/9901001`

## Requirements

- Python 3.10+
- A DeepSeek-compatible API key
- A local TeX distribution for compilation, preferably with `latexmk` and `xelatex`

The translator uses an OpenAI-compatible chat completions endpoint configured in
`config.local.json`. All fields shown below are required.

## API key config

Copy `config.local.example.json` to `config.local.json`, then put your API key there:

```json
{
  "deepseek_api_key": "sk-your-deepseek-api-key",
  "deepseek_model": "deepseek-v4-pro",
  "deepseek_guide_model": "deepseek-v4-flash",
  "deepseek_base_url": "https://api.deepseek.com/chat/completions"
}
```

`config.local.json` is ignored by git so the key stays local to your machine.

## Usage

```powershell
python -m arxiv_translate https://arxiv.org/abs/2401.00001
```

Run without a link to enter interactive mode. Each input line triggers the full
workflow for one paper:

```powershell
python -m arxiv_translate
arxiv> https://arxiv.org/abs/2401.00001
arxiv> 2402.00002
arxiv> exit
```

On Windows, you can also double-click `arxiv_translate_interactive.cmd` in the
project folder to open the same interactive mode. The launcher forwards options,
so `arxiv_translate_interactive.cmd --redo` opens interactive mode with forced
reruns. In that Windows interactive console, Up/Down recalls previous inputs,
and history is saved locally in `.arxiv_translate_history`.

Useful flags:

```powershell
python -m arxiv_translate https://arxiv.org/pdf/2401.00001.pdf --no-compile
python -m arxiv_translate 2401.00001 --main paper.tex
python -m arxiv_translate 2401.00001 --chunk-chars 4096 --context-chars 500 --parallel-chunks 4
python -m arxiv_translate 2401.00001 --redo
python -m arxiv_translate https://arxiv.org/html/2401.00001 --keep-source-archive
```

If the output directory already contains a completed result, the command skips
the paper before making network or DeepSeek requests. Use `--redo` to force the
full workflow again.

By default, each translation request sends one TeX chunk of up to 4096
characters plus 500 characters of previous context and 500 characters of next
context. The prompt instructs DeepSeek to use the context only for terminology
and coherence, and to output only the current chunk translation without repeated
context.

The tool sends up to 4 translation chunks concurrently by default. Use
`--parallel-chunks 1` for strictly sequential requests, or lower the value if
the API rate limit is tight.

During translation, the command prints a compact chunk progress bar so long
papers have visible forward progress.

Chunks are split only at paragraph boundaries. If a single paragraph is longer
than the chunk size, it is kept intact rather than split in the middle.

Before chunk translation, the tool sends the full TeX source once to
`deepseek_guide_model` and caches a concise `paper-guide.md` with the paper
structure, glossary, style rules, and LaTeX cautions. Later translation requests
prepend that fixed guide before dynamic context to improve terminology
consistency and cacheability.

Output layout:

```text
arxiv_outputs/
  2401.00001/
    original.pdf         # original arXiv PDF
    endnote.enw          # EndNote Import file with metadata and attachments
    paper-guide.md       # cached whole-paper translation guide
    source/              # extracted original source
    translated/          # translated TeX tree, including translate.pdf after compile
      compile.log        # LaTeX compiler output when compilation runs
    source-download.bin  # optional with --keep-source-archive
    translation-cache.json
```

Use `--output-dir runs` to save under `runs/{arxiv-id}/` instead.

If arXiv has no TeX source for the paper, the command still writes
`original.pdf` and `endnote.enw`, but skips translation and compilation.

To add the record to EndNote, import `endnote.enw` with the `EndNote Import`
filter. The file includes arXiv metadata plus file attachment entries for
`original.pdf`; it also includes the translated PDF when TeX translation and
compilation succeeds.

## Tests

```powershell
python -m unittest discover -s tests
```
