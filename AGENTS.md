# AGENTS.md

## Project Goal

This repository maintains a Simplified Chinese localization of YASB.

When working on localization-related tasks, the primary objective is to produce a complete, natural, maintainable `zh-CN` translation while preserving upstream behavior and minimizing unrelated code changes.

Localization work must follow the existing architecture of the project. Do not introduce a separate i18n system unless the existing implementation cannot support the required functionality.

---

## Repository Workflow

The repository uses the following branch roles:

* `upstream`: mirror of the original upstream project's main branch
* `i18n`: active localization and integration branch
* `main`: tested and publishable localized branch

Normal localization work must be performed on `i18n`.

Do not modify, reset, rebase, merge into, or commit directly to `upstream` or `main` unless explicitly instructed.

Do not push to any remote repository unless explicitly requested.

Never run destructive Git operations such as:

```bash
git reset --hard
git clean -fd
git clean -fdx
git push --force
git push --force-with-lease
```

Do not discard existing uncommitted user changes.

Before making significant changes, inspect the current branch and working tree state.

---

## Scope Discipline

Keep localization changes focused.

Do not perform unrelated:

* refactoring
* dependency upgrades
* code cleanup
* formatting of unrelated files
* API redesign
* file reorganization
* architectural changes

If a small code change is necessary to make localization work correctly, keep it minimal and explain why it is required.

Avoid large formatting-only diffs. Preserve the surrounding style of files whenever practical.

---

## Localization Principles

Translate according to UI context, not word-for-word.

Translations should read like native Simplified Chinese software UI written for users in mainland China.

Prefer concise UI wording.

Preserve the meaning, tone, and functional intent of the original text.

Avoid machine-translation-style phrasing, unnecessary literal translations, and awkward sentence structures.

When a string is ambiguous, inspect:

* where it is used
* the related widget or UI component
* nearby code
* screenshots or UI structure if available
* related strings

Do not guess based only on an isolated English string when contextual evidence is available.

---

## Terminology Consistency

Use consistent terminology throughout the project.

Preferred translations include:

| English       | Simplified Chinese |
| ------------- | ------------------ |
| Settings      | 设置               |
| General       | 常规               |
| Appearance    | 外观               |
| Widget        | 小组件             |
| Taskbar       | 任务栏             |
| System tray   | 系统托盘           |
| Workspace     | 工作区             |
| Window        | 窗口               |
| Monitor       | 显示器             |
| Display       | 显示               |
| Notification  | 通知               |
| Update        | 更新               |
| Refresh       | 刷新               |
| Restart       | 重新启动           |
| Reload        | 重新加载           |
| Enable        | 启用               |
| Disable       | 禁用               |
| Default       | 默认               |
| Custom        | 自定义             |
| Configuration | 配置               |
| Profile       | 配置文件           |
| Theme         | 主题               |
| Layout        | 布局               |
| Preview       | 预览               |
| Apply         | 应用               |
| Cancel        | 取消               |
| Save          | 保存               |
| Reset         | 重置               |
| Close         | 关闭               |

This table is guidance rather than a blind substitution dictionary.

Context takes priority. For example, `Display` may refer to a physical monitor or to the act of showing content depending on context.

When introducing a translation for a recurring technical term, search existing translations first and reuse established terminology whenever appropriate.

---

## Text That Should Normally Be Localized

Localize user-facing content such as:

* menus
* buttons
* settings labels
* setting descriptions
* dialogs
* tooltips
* notifications
* user-facing errors and warnings
* tray menu entries
* widget names
* widget descriptions
* onboarding text
* visible status messages
* other text presented directly to users

---

## Text That Should Normally NOT Be Localized

Do not translate internal or machine-readable content unless the project architecture explicitly requires it.

Examples include:

* variable names
* function names
* class names
* module names
* configuration keys
* JSON/YAML/TOML keys
* internal IDs
* enum values
* protocol values
* API names
* command names
* CLI arguments
* environment variable names
* filesystem paths
* URLs
* package names
* project names
* technical identifiers
* CSS selectors
* Qt object names
* log messages intended exclusively for developers

Do not translate proper names or technical terms that do not have a useful established Chinese equivalent merely for the sake of removing English text.

---

## Preserve Runtime-Sensitive Content

When translating strings, preserve all runtime-sensitive syntax exactly.

This includes, but is not limited to:

```text
{name}
{value}
{0}
{}
%s
%d
%(name)s
${variable}
{{variable}}
```

Also preserve:

* HTML/XML tags
* Markdown structure
* escape sequences
* newlines where semantically required
* keyboard shortcuts
* accelerator markers
* command examples
* code snippets
* URLs
* file paths
* formatting directives
* Unicode characters with functional meaning

Never add, remove, rename, or reorder placeholders unless the formatting system explicitly supports it and the change is required by Chinese grammar.

Before considering a translation complete, compare placeholders between the source and translated strings.

---

## User-Facing Errors

User-facing errors should be translated naturally while preserving technical information useful for troubleshooting.

Do not translate identifiers embedded in an error when doing so would make debugging harder.

For example, preserve items such as:

```text
config.yaml
PATH
HTTP 403
ConnectionError
WidgetManager
```

while translating the surrounding human-readable explanation.

---

## Translation Style

Prefer:

```text
启用此功能
```

over overly formal wording such as:

```text
对此功能进行启用
```

Prefer:

```text
无法加载配置文件
```

over mechanically translated wording such as:

```text
加载配置文件失败了
```

Prefer concise labels:

```text
自动隐藏
```

instead of:

```text
自动隐藏任务栏功能
```

when the surrounding UI already establishes the subject.

Avoid unnecessary punctuation in short UI labels.

Use Chinese punctuation in normal Chinese sentences, but never alter punctuation that has syntactic or formatting significance.

---

## English Text Audit

Do not assume localization is complete merely because all translation resource entries were processed.

Before completion, search the repository for remaining user-visible English text.

For each remaining English string, determine whether it is:

1. intentionally retained
2. internal/non-user-facing
3. a proper name or technical identifier
4. an untranslated user-facing string

Only category 4 should normally be localized.

Do not blindly translate every English string returned by repository-wide search.

---

## Duplicate and Similar Strings

When multiple source strings express the same concept, prefer consistent Chinese wording.

However, do not force identical translations when context differs.

Examples:

```text
Open
```

may mean:

```text
打开
```

for a file or window, but another translation may be appropriate in a different grammatical context.

Always inspect usage before normalizing ambiguous strings.

---

## Existing Translations

Treat existing Chinese translations as project conventions, but not as automatically correct.

Before changing an established translation:

1. inspect how widely it is used
2. determine whether it is actually incorrect or inconsistent
3. consider whether changing it improves overall terminology consistency

Avoid unnecessary churn in existing translations.

---

## Source Changes

When upstream code introduces new user-facing strings, add corresponding `zh-CN` translations as part of localization work.

When upstream removes or renames strings, update localization resources accordingly.

Do not preserve obsolete translation entries solely because they existed previously unless the localization system intentionally supports unused fallback entries.

---

## Validation

After localization changes, run the most relevant validation available in the repository.

Prefer existing project commands and tooling rather than inventing custom validation unnecessarily.

Validation should include, where applicable:

* syntax/parsing checks
* localization resource validation
* lint
* unit tests
* relevant application tests
* placeholder consistency checks
* loading `zh-CN`
* repository-wide untranslated UI text audit

If running the full test suite is impractical, run the subset most relevant to the files changed.

Do not claim a test passed unless it was actually executed successfully.

If a validation command fails because of an existing unrelated problem, distinguish that clearly from failures introduced by the current change.

---

## UI Considerations

Chinese text frequently has different width characteristics from English.

When modifying UI-related localization, watch for:

* clipped labels
* truncated descriptions
* fixed-width controls
* line wrapping
* menu width
* tooltip readability
* punctuation spacing

Do not redesign layouts preemptively.

Only modify layout code when there is evidence that localization causes an actual UI problem, and keep such changes minimal.

---

## Investigation Before Editing

Before modifying an unfamiliar localization area:

1. inspect the relevant files
2. understand how strings are loaded
3. find similar existing translations
4. inspect call sites for ambiguous strings
5. then edit

Do not make broad substitutions without understanding how the text is used.

---

## Autonomous Work

For a clearly defined localization task, continue working through related files and validation without repeatedly asking for confirmation.

Do not stop merely because the task spans many files.

Stop and report the blocker only when progress genuinely requires information or access that cannot be inferred or obtained from the repository.

When uncertain but the risk is low, make the most conservative reasonable change.

When uncertainty could alter program behavior or corrupt localization resources, investigate further before editing.

---

## Completion Standard

Localization work is considered complete only when:

* requested user-facing areas are translated
* translations are natural Simplified Chinese
* terminology is reasonably consistent
* placeholders and formatting are preserved
* localization resources remain valid
* no unrelated large-scale changes are included
* relevant validation has been run
* remaining English UI strings have been reviewed rather than blindly ignored

At the end of substantial localization work, summarize:

* major areas translated
* important files changed
* validation performed
* remaining uncertain strings or areas requiring manual review

Keep the summary concise and factual.
