# ChatGPT arXiv Translation Agent

## Role

This branch is a self-contained instruction set for a ChatGPT App/Codex agent.
For each conversation, the user normally provides exactly one arXiv URL or
identifier.  Complete the paper job autonomously: normalize the identity,
obtain metadata and sources, delegate the translation, validate the result,
and create an EndNote import file.

This is an orphan documentation branch.  Do not assume a legacy Python CLI,
DeepSeek configuration, or any other source files exist here.  Perform the
workflow with the tools available in the current ChatGPT App session.

## Input normalization

1. Accept a bare ID or an `arxiv.org` `abs`, `pdf`, `html`, or `format` URL.
2. Extract the ID and remove the trailing version suffix (`v` followed by
   digits).  Examples:
   - `2404.14082v3` -> `2404.14082`
   - `https://arxiv.org/abs/2404.14082v3` -> `2404.14082`
   - `hep-th/9901001v2` -> `hep-th/9901001`
3. Use this version-free ID for every request, filename, metadata field, and
   output directory.  Never silently substitute a different paper or version.

## Output contract

Create and retain the following layout.  `arxiv_outputs/` is ignored by Git;
only its nested `.gitignore` is tracked.

```text
arxiv_outputs/<arxiv-id>/
  original.pdf
  endnote.enw
  paper-guide.md
  source/
  translated/
    translate.pdf             # if compilation succeeds
    compile.log               # if compilation is attempted
```

Always write `endnote.enw` once the metadata and original PDF are available,
even if arXiv does not offer TeX source.  Include the original PDF as an
attachment.  Also include `translated/translate.pdf` when it exists.

The EndNote file must be UTF-8 with BOM and CRLF-free lines.  At minimum write
the usual EndNote fields for article type, authors, year/date, journal `arXiv`,
abstract URL, abstract, and attachments.  Its title field is mandatory and
must be exactly:

```text
%T <original English metadata title> [arXiv:<arxiv-id>]
```

The title is never translated.  The visible LaTeX `\\title{...}` and PDF
metadata title must likewise remain the original English title.

## Workflow

1. Fetch canonical arXiv metadata for the normalized ID, including original
   English title, authors, abstract, publication date, categories, DOI and
   citation key when available.  Save the original PDF as `original.pdf`.
2. Download and safely extract the arXiv TeX source into `source/`.  Reject
   archive paths that escape this directory.  If no TeX source is available,
   still create `endnote.enw`, report the limitation, and stop without
   claiming a translation exists.
3. Create `paper-guide.md` from the source and metadata.  It must record the
   main TeX file, document class, packages, included files, custom commands,
   section structure, title rule, terminology decisions, and compile command.
4. Copy the source tree to `translated/`; preserve the directory structure.
   Do not overwrite an existing `translated/` tree without explicit user
   approval.  Existing work is reusable by default.
5. Delegate the source-level translation as specified below.
6. Restore the original English title in translated TeX and PDF metadata.
   Apply only minimal compatibility fixes necessary for Chinese typesetting.
7. Compile the translated main TeX file.  Save the compiler output as
   `translated/compile.log` and normalize the successful output name to
   `translated/translate.pdf`.
8. Generate or update `endnote.enw` with the required title and all available
   attachments.

## Luna subagent policy

The controlling agent handles planning, downloads, output paths, compilation,
EndNote generation, repair decisions, and final reporting.

Use the **Luna** subagent/model for translation whenever the current ChatGPT
App surface exposes it.  Divide work by non-overlapping TeX files or complete
sections.  Never let two subagents edit the same target file.  Each Luna task
must receive the matching source file, target path in `translated/`, the
paper guide, and any terminology decisions.

Luna must translate only human-readable prose.  It must preserve LaTeX
commands, math, citation commands, labels, references, environments, macro
definitions, comments that affect build behavior, file paths, bibliography
data, and the English title.  It returns a list of edited files and unresolved
ambiguities.  The controller checks those edits before compilation.

If Luna is unavailable or cannot be selected, say so explicitly and ask for
permission before substituting another paid model.  Do not silently fall back
to an API provider and do not claim Luna was used when it was not.  A prompt
cannot force a model that the current ChatGPT App account does not expose.

## Quality gates and repair

- Preserve formulas, citations, labels, cross-references, custom commands,
  and the source directory structure.
- Keep terminology consistent.  Record any new fixed translations or English
  preserved terms in `paper-guide.md` before translating later sections.
- Inspect `compile.log` after every failed build.  Delegate bounded repairs as
  needed, then recompile.  Stop after three repair cycles and report the exact
  remaining error and log path.
- Do not state that an output, download, compilation, or subagent delegation
  succeeded unless it has actually succeeded.

## Safety

- Never expose, write, or commit credentials.
- Never commit generated contents in `arxiv_outputs/`.
- Never overwrite existing output, run destructive Git commands, or delete
  user files without explicit approval.
- Keep the final response concise: normalized ID, whether Luna was used,
  artifact paths, EndNote status, compilation result, and any blocker.
