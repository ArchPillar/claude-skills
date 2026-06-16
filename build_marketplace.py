#!/usr/bin/env python3
"""Build (and optionally publish) a source repo's Claude Code skills into this shared marketplace.

This is the **canonical builder** for the ArchPillar skills marketplace. It lives here, in the
marketplace repo, so every source repo shares one implementation with no drift: a source repo's
publish/CI workflows clone this repo and run this script against their own checkout (see
`templates/source-repo/` for the copy-paste publishing kit).

Each source repo is the source of truth for its own skills; this script emits a self-contained plugin
tree and merges it into a checkout of this marketplace repo on release — the way a NuGet publish packs
a library. Two manifests make the multi-repo model explicit and auditable:

  * Source manifest (`tools/skill-marketplace/skills.json`, read from --source-root) — what THAT repo
    publishes. A skill ships only if it is listed AND its package is published (present in the source
    repo's `.github/workflows/publish.yml`): declared intent, gated by what actually ships, no
    hardcoded list in code.
  * Marketplace provenance (`.claude-plugin/sources.json` here) — records which source repo (and
    version) each plugin came from. The builder uses it to add/update one repo's plugins and to DELETE
    ones that repo previously owned but no longer publishes, without touching plugins owned by other
    repos. `marketplace.json` is regenerated as the union.

Only the generated artifacts are written into --into: `.claude-plugin/marketplace.json`,
`.claude-plugin/sources.json`, and `plugins/`. The hand-maintained `README.md`, this builder, and
`templates/` are never touched.

Usage:
    # Validate a source repo's manifest (PR-time check, no build):
    python3 build_marketplace.py --check --source-root /path/to/source
    # Preview a source repo's staged plugins without merging:
    python3 build_marketplace.py --source-root /path/to/source --version 1.4.4
    # Build and merge into a marketplace checkout (release publish):
    python3 build_marketplace.py --source-root /path/to/source --into /path/to/claude-skills --version 1.4.4
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SKILL_PREFIX = "archpillar-"
LEAD_PARAGRAPH_CAP = 500  # max length of a fallback plugin description derived from SKILL.md


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def plugin_dir_name(skill: str) -> str:
    """archpillar-mapper -> mapper (the plugin folder under plugins/)."""
    return skill[len(SKILL_PREFIX):] if skill.startswith(SKILL_PREFIX) else skill


def derive_package(lib: str) -> str:
    """mapper -> ArchPillar.Extensions.Mapper (PascalCase each hyphen segment)."""
    pascal = "".join(seg[:1].upper() + seg[1:] for seg in lib.split("-"))
    return f"ArchPillar.Extensions.{pascal}"


def check_manifest(manifest: dict, source_root: Path) -> list[str]:
    """Validate skills.json against the source repo. Returns a list of errors (empty == OK).

    Guards the bookkeeping: every listed skill must exist, and every *published* skill present
    under .claude/skills/ must be listed (else it would silently never ship to the marketplace).
    """
    skills_dir = source_root / ".claude" / "skills"
    publish_yml = (source_root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    errors: list[str] = []
    listed: dict[str, str] = {}

    for entry in manifest["skills"]:
        name = entry["name"]
        if name in listed:
            errors.append(f"duplicate manifest entry: {name}")
        package = entry.get("package") or derive_package(plugin_dir_name(name))
        listed[name] = package
        if not (skills_dir / name / "SKILL.md").is_file():
            errors.append(f"manifest lists '{name}' but {skills_dir}/{name}/SKILL.md is missing")
        if package not in publish_yml:
            print(f"WARN: '{name}' -> {package} is not published yet; it will be skipped until it is")

    for skill_dir in sorted(skills_dir.glob(f"{SKILL_PREFIX}*")):
        if not (skill_dir / "SKILL.md").is_file():
            continue
        name = skill_dir.name
        package = derive_package(plugin_dir_name(name))
        if package in publish_yml and name not in listed:
            errors.append(
                f"published skill '{name}' ({package}) is not listed in the manifest — "
                f"it will never publish to the marketplace"
            )
    return errors


def lead_paragraph(skill_md: Path) -> str:
    """Lead paragraph of the SKILL.md body: the full first paragraph after frontmatter and the H1.

    The fallback plugin description when the source manifest carries no explicit one. Markdown
    emphasis is stripped and the paragraph collapsed to a single line, capped at ~500 chars (cut on
    a word boundary, with an ellipsis, when it runs long).
    """
    text = skill_md.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    body: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            if body:
                break
            continue
        body.append(s)
    para = re.sub(r"\*\*|`|\*", "", " ".join(body))
    para = re.sub(r"\s+", " ", para).strip()
    if len(para) <= LEAD_PARAGRAPH_CAP:
        return para
    return para[:LEAD_PARAGRAPH_CAP].rsplit(" ", 1)[0].rstrip() + "…"


def build_staging(args, manifest: dict, out: Path, source_root: Path) -> dict:
    """Emit the source repo's plugins into `out/plugins/<dir>/`. Returns {skill_name: dir_name}."""
    skills_dir = source_root / ".claude" / "skills"
    publish_yml = (source_root / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    produced: dict[str, str] = {}
    for entry in manifest["skills"]:
        name = entry["name"]
        package = entry.get("package", f"ArchPillar.Extensions.{plugin_dir_name(name).capitalize()}")
        skill_dir = skills_dir / name

        if not (skill_dir / "SKILL.md").is_file():
            print(f"ERROR: manifest lists '{name}' but {skill_dir}/SKILL.md is missing", file=sys.stderr)
            raise SystemExit(1)
        if package not in publish_yml:
            msg = f"skill '{name}' -> {package} not published (absent from publish.yml)"
            if args.require_published:
                print(f"ERROR: {msg}", file=sys.stderr)
                raise SystemExit(1)
            print(f"SKIP: {msg}")
            continue

        lib = plugin_dir_name(name)
        plugin_dir = out / "plugins" / lib
        (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, plugin_dir / "skills" / name)
        write_json(plugin_dir / ".claude-plugin" / "plugin.json", {
            "name": name,
            "version": args.version,
            "description": entry.get("description") or lead_paragraph(skill_dir / "SKILL.md"),
            "author": {"name": args.author_name},
            "homepage": args.source_repo,
            "repository": args.source_repo,
            "license": args.license,
            "keywords": ["archpillar", lib, "dotnet", "agent-skill"],
        })
        produced[name] = lib
        print(f"OK:   {name} ({package}) -> plugins/{lib}")

    if not produced:
        print("ERROR: no published skills to publish", file=sys.stderr)
        raise SystemExit(1)
    return produced


def regenerate_marketplace(target: Path, args, marketplace_name: str) -> int:
    """Rebuild marketplace.json from every plugin currently in `target/plugins/` (the union).

    Regenerates only the marketplace manifest — the hand-maintained README, this builder, and
    templates/ are deliberately left untouched.
    """
    plugins = []
    for pj in sorted((target / "plugins").glob("*/.claude-plugin/plugin.json")):
        data = read_json(pj)
        plugins.append({"name": data["name"], "source": f"./plugins/{pj.parents[1].name}",
                        "description": data.get("description", "")})
    plugins.sort(key=lambda p: p["name"])

    write_json(target / ".claude-plugin" / "marketplace.json",
               {"name": marketplace_name, "owner": {"name": args.author_name}, "plugins": plugins})
    return len(plugins)


def merge_into(target: Path, staging: Path, produced: dict, args, marketplace_name: str) -> None:
    """Apply the source repo's published set to `target`, deleting plugins it no longer publishes."""
    (target / "plugins").mkdir(parents=True, exist_ok=True)
    prov_path = target / ".claude-plugin" / "sources.json"
    provenance = read_json(prov_path).get("plugins", {}) if prov_path.is_file() else {}

    # Delete plugins THIS repo previously owned but no longer publishes (clean unpublish).
    ours_before = {n for n, p in provenance.items() if p.get("sourceRepo") == args.source_repo}
    for name in ours_before - produced.keys():
        gone = target / "plugins" / provenance[name].get("dir", plugin_dir_name(name))
        if gone.exists():
            shutil.rmtree(gone)
        provenance.pop(name, None)
        print(f"DEL:  {name} (was {args.source_repo}, no longer published)")

    # Add/update this repo's plugins + provenance.
    for name, lib in produced.items():
        dest = target / "plugins" / lib
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(staging / "plugins" / lib, dest)
        provenance[name] = {"sourceRepo": args.source_repo, "version": args.version, "dir": lib}

    write_json(prov_path, {"plugins": dict(sorted(provenance.items()))})
    total = regenerate_marketplace(target, args, marketplace_name)
    print(f"\nPublished {len(produced)} plugin(s) from {args.source_repo}; marketplace lists {total}.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source-root", default=".",
                   help="source repo to read .claude/skills/, the manifest, and publish.yml from")
    p.add_argument("--manifest", default="tools/skill-marketplace/skills.json",
                   help="source manifest, relative to --source-root unless absolute")
    p.add_argument("--out", default="tools/skill-marketplace/dist",
                   help="staging dir, relative to --source-root unless absolute")
    p.add_argument("--into", help="checkout of this marketplace repo to merge into")
    p.add_argument("--version", default="0.0.0-dev")
    p.add_argument("--source-repo", help="override the manifest sourceRepo (e.g. in CI)")
    p.add_argument("--marketplace-repo", help="override the manifest marketplace.repo")
    p.add_argument("--author-name", default="ArchPillar")
    p.add_argument("--license", default="MIT")
    p.add_argument("--require-published", action="store_true")
    p.add_argument("--check", action="store_true", help="validate the manifest and exit (no build)")
    args = p.parse_args()

    source_root = Path(args.source_root).resolve()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = source_root / manifest_path
    manifest = read_json(manifest_path)

    if args.check:
        errors = check_manifest(manifest, source_root)
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        if errors:
            return 1
        print("Manifest OK")
        return 0

    args.source_repo = args.source_repo or manifest["sourceRepo"]
    args.marketplace_repo = args.marketplace_repo or manifest["marketplace"]["repo"]
    marketplace_name = manifest["marketplace"]["name"]

    staging = Path(args.out)
    if not staging.is_absolute():
        staging = source_root / staging

    produced = build_staging(args, manifest, staging, source_root)
    if args.into:
        merge_into(Path(args.into).resolve(), staging, produced, args, marketplace_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
