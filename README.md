# ArchPillar Claude skills marketplace

A [Claude Code](https://claude.com/claude-code) plugin marketplace for the published
**ArchPillar.Extensions** libraries. Each plugin packages one library's Agent Skill so an AI assistant
uses the library the way it is designed to be used.

This repo is a **generated mirror**. The skills themselves are authored and tested in their source
repositories (e.g. [`ArchPillar/extensions`](https://github.com/ArchPillar/extensions) under
`.claude/skills/`); a release in a source repo publishes its skills here. Do not hand-edit the
generated artifacts — see [What is generated vs. hand-maintained](#what-is-generated-vs-hand-maintained).

## Install

In Claude Code:

```text
/plugin marketplace add ArchPillar/claude-skills
/plugin install <name>@archpillar
```

`<name>` is the skill/plugin name (for example `archpillar-mapper` or `archpillar-localization`); the
available plugins are listed in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json).

## What is generated vs. hand-maintained

| Path | Maintained by | Notes |
|------|---------------|-------|
| `.claude-plugin/marketplace.json` | **Generated** | The union of every plugin currently published. |
| `.claude-plugin/sources.json` | **Generated** | Provenance: which source repo + version each plugin came from. |
| `plugins/<lib>/` | **Generated** | One plugin per published library. |
| `build_marketplace.py` | Hand-maintained | The canonical builder, shared by every source repo. |
| `templates/source-repo/` | Hand-maintained | The copy-paste publishing kit for a new source repo. |
| `README.md` | Hand-maintained | This file. |

The builder regenerates **only** the three generated entries above and never overwrites the
hand-maintained files, so a publish from one source repo only ever adds/updates/removes its own
plugins (tracked via `sources.json`) — other repos' plugins are left in place.

## How publishing works

The monorepo model mirrors NuGet publishing: a source repo is the source of truth, this marketplace is
the generated artifact.

- Each source repo declares the skills it publishes in a **source manifest**
  (`tools/skill-marketplace/skills.json`). A skill ships only if it is listed **and** its package is
  published (present in that repo's `.github/workflows/publish.yml`) — declared intent, gated by what
  actually ships.
- On `release: published`, the source repo's `publish-skills.yml` workflow clones this repo, runs the
  canonical `build_marketplace.py` against its own checkout (`--source-root`), and pushes the
  regenerated artifacts directly to `main`. This is a generated artifact repo, so there is no PR flow.
- `build_marketplace.py --check` is run at PR time in each source repo to keep the manifest honest.

## Onboarding a new source repo

To publish a repo's skills into this marketplace, copy the kit in
[`templates/source-repo/`](templates/source-repo/) into that repo and fill in the placeholders:

1. `tools/skill-marketplace/skills.json` — set `sourceRepo` and list the repo's skills
   (`{ "name": "archpillar-<library>", "package": "<NuGet.Package.Id>" }`).
2. `.github/workflows/publish-skills.yml` — the release publish. It clones this repo and runs the
   canonical builder; no edits needed beyond copying it in.
3. `.github/workflows/check-skills.yml` — the PR-time manifest check (or fold its `skills-manifest`
   job into the repo's existing CI workflow).

Then configure the publishing **GitHub App secrets** on the source repo:

| Secret | Purpose |
|--------|---------|
| `SKILLS_APP_ID` | App ID of the org-owned GitHub App scoped to this marketplace repo (Contents: write). |
| `SKILLS_APP_PRIVATE_KEY` | The App's private key (PEM). |

The workflow mints a short-lived installation token from these at runtime — no personal access token
is stored. The PR-time check needs no secret because this marketplace repo is public.

## License

[MIT](LICENSE)
