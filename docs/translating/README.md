# Translating the documentation

English is the source of the documentation. Each translation is a complete,
page-for-page mirror of it: no summaries, no extra content. Accuracy comes
before fluency. If the English is wrong, fix the English first, then carry the
fix into each translation.

Each language has its own guide covering terminology, typography and
admonition wording:

- [Simplified Chinese](zh.md)

## Layout

- `docs/en/` holds the English pages. `docs/<lang>/` holds a translation, and
  every page keeps the English path: `docs/en/learn/udp.md` becomes
  `docs/<lang>/learn/udp.md`.
- `zensical.toml` is the only site configuration. `docs/build.py` builds
  English into `site/`, then each translation into `site/<lang>/` from the
  same configuration with the values in `docs/translating/<lang>.toml`
  applied: the site description, the navigation section labels and the color
  scheme toggle labels.
- A page's navigation title is the `title` in its front matter, so each
  language titles its own pages and the navigation needs no translation.
- Brand assets and stylesheets are in `docs/overrides/` (the theme's
  `custom_dir`), so every language shares them.
- Pages pull code and repository files in with `--8<--` snippets. Every
  language includes the same files, so code exists only once.

## Language switcher

`zensical.toml` lists every language under `[[project.extra.alternate]]`, and
every language's site uses that list:

```toml
[[project.extra.alternate]]
name = "English"   # the language's name, written in that language
link = "/"         # root of that language's site
lang = "en"        # language code

[[project.extra.alternate]]
name = "简体中文"
link = "/zh/"
lang = "zh"
```

The switcher takes the reader to the root of the other language's site.

## Add a language

1. Create `docs/<lang>/` with a page for every English page, at the same path.
   Copy any page you have not translated yet from English and give it the lag
   banner (see [Keep translations in sync](#keep-translations-in-sync)).
2. Copy `docs/translating/zh.toml` to `docs/translating/<lang>.toml` and
   translate its values.
3. Add the new language's `[[project.extra.alternate]]` entry to
   `zensical.toml`.
4. Write `docs/translating/<lang>.md` and link it from the list at the top of
   this file. It must cover terminology tiers, a glossary, typography,
   admonition titles and how to cite RFC sections.
5. Build every language:

   ```console
   uv run --locked --group docs python docs/build.py --strict
   ```

   Every build must report no issues. Open `site/<lang>/` and check the
   switcher, the navigation and a few heading anchors.

## What is never translated

- Code blocks, snippet lines (`--8<--`) and the files they include. Mermaid
  diagrams are the exception: translate their labels and notes, and keep
  identifiers such as method calls and class names unchanged.
- Example output (`text` and `console` blocks), including `repr()` output and
  error messages.
- Identifiers in inline code: modules, classes, functions, parameters,
  attributes, enum members, events, configuration fields, environment
  variables, commands and paths.
- API reference. Its content comes from the `.pyi` docstrings through
  mkdocstrings (`::: ngquic.TLSContext`) and is always rendered in English.
  On a reference page, translate the title, the `description` and the
  surrounding prose, and copy every `:::` line unchanged.
- Project, library and standard names, RFC titles, and benchmark environment
  lines.

To check that the verbatim parts of a page match the English (Mermaid
fences are compared, their contents are not):

```console
v() { awk '/^ *```/{if(!f)m=/mermaid/;f=!f;print;next} (f&&!m)||/^ *(--8<--|:::)/' "$1"; }
diff <(v docs/en/<path>.md) <(v docs/<lang>/<path>.md)
```

## Page rules

- **Front matter**: translate `title`, which names the page in the
  navigation, and `description`. Add `source_commit` (see
  [Keep translations in sync](#keep-translations-in-sync)).
- **Heading anchors**: every heading below the page title carries the anchor
  that the English heading generates, so all languages share anchors:
  `## <translated heading> {#who-owns-what}`. Without an explicit anchor, a
  heading's id depends on its wording, and the default slugify drops
  non-ASCII characters, turning a heading such as `## 连接迁移` into `_1`.
  To find the English anchor, open the English page and copy the target of
  the heading's permalink (`¶`). Headings that mkdocstrings generates already
  share their ids across languages.
- **Admonitions**: always write the title out in the target language,
  `!!! warning "<title>"`. The theme otherwise shows the English type name.
  The language guide lists the wording.
- **Links**: links between pages stay relative and unchanged, so each one
  resolves inside the reader's own language. Links to RFCs and external
  sites stay as they are.
- **RFC citations**: English writes `RFC 9000 §10.2`, linked to the section.
  Each language guide fixes one form for its language. Keep the link target
  unchanged.
- **Terminology**: use the language guide's glossary. A term that is missing
  from it gets added in the same pull request. A change to a rendering
  updates every page in that pull request.

## Keep translations in sync

Every translated page records the English commit it was last fully synced
with:

```yaml
---
description: ...
source_commit: 1a2b3c4
---
```

To list English changes the page has not caught up with:

```console
git log --oneline <source_commit>..HEAD -- docs/en/<path>.md
```

A pull request that changes an English page should update its translations
and their `source_commit`. If it cannot, it keeps `source_commit` as it was and
puts a lag banner under the page title, written in the page's language:

```markdown
!!! warning "<translation is out of date>"
    <This page lags behind the [English original](/<path>/); the English page is authoritative.>
```

Once the page has caught up, remove the banner and update `source_commit`. A
new English page gets an English copy with the banner straight away, so the
switcher never leads to a missing page.

## Review

- Every new or changed translation is reviewed by a reader fluent in the
  language who also checks it against the English.
- The reviewer checks that the path and anchors match the English page, that
  `source_commit` is set, that the verbatim-parts `diff` above prints nothing,
  that the glossary was followed, and that both builds report no issues.
- Fix a meaning error in the same pull request. A matter of style that the
  language guide does not settle goes into that guide first.
