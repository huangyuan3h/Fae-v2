"""Load Skill markdown files with YAML frontmatter."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from fae.agent.skills_schema import LoadStrategy, Skill, SkillMetadata

logger = logging.getLogger("fae.agent.skills")

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def default_skills_dir() -> Path:
    """`backend/src/skills` (sibling of the `fae` package)."""
    return Path(__file__).resolve().parents[2] / "skills"


def parse_skill_markdown(raw: str, *, path: Path | None = None) -> Skill:
    """Parse one skill document; raise ValueError on bad frontmatter."""
    text = raw.lstrip("\ufeff")
    match = _FRONTMATTER.match(text)
    if not match:
        raise ValueError("missing YAML frontmatter (--- ... ---)")
    meta_raw, body = match.group(1), match.group(2).strip()
    try:
        data = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    if "load_strategy" in data and isinstance(data["load_strategy"], str):
        data["load_strategy"] = data["load_strategy"].lower().replace("-", "_")
    try:
        meta = SkillMetadata.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"invalid skill metadata: {e}") from e
    return Skill(meta=meta, body=body, path=path, raw_markdown=text)


class SkillsLoader:
    """Scan a directory; cache by mtime."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.skills_dir = skills_dir or default_skills_dir()
        self._cache: dict[str, Skill] = {}
        self._mtimes: dict[str, float] = {}

    def reload(self) -> list[Skill]:
        self._cache.clear()
        self._mtimes.clear()
        return self.list_skills()

    def list_skills(self) -> list[Skill]:
        root = self.skills_dir
        if not root.is_dir():
            logger.warning("skills dir missing: %s", root)
            return []
        names: set[str] = set()
        for path in sorted(root.glob("*.md")):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = path.name
            if key in self._mtimes and self._mtimes[key] == mtime:
                names.add(self._cache[key].meta.name)
                continue
            try:
                skill = parse_skill_markdown(path.read_text(encoding="utf-8"), path=path)
            except ValueError:
                logger.exception("skip invalid skill %s", path)
                continue
            self._cache[key] = skill
            self._mtimes[key] = mtime
            names.add(skill.meta.name)
        # Drop stale cache entries
        for key in list(self._cache):
            if not (root / key).is_file():
                self._cache.pop(key, None)
                self._mtimes.pop(key, None)
        return sorted(self._cache.values(), key=lambda s: s.meta.name)

    def get(self, name: str) -> Skill | None:
        for skill in self.list_skills():
            if skill.meta.name == name:
                return skill
        return None

    def write_skill(self, name: str, raw_markdown: str) -> Skill:
        """Validate and write a skill file named after meta.name."""
        skill = parse_skill_markdown(raw_markdown)
        if skill.meta.name != name:
            raise ValueError(
                f"frontmatter name '{skill.meta.name}' != path name '{name}'"
            )
        root = self.skills_dir
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{name}.md"
        path.write_text(raw_markdown if raw_markdown.endswith("\n") else raw_markdown + "\n", encoding="utf-8")
        skill = parse_skill_markdown(path.read_text(encoding="utf-8"), path=path)
        self._cache[path.name] = skill
        self._mtimes[path.name] = path.stat().st_mtime
        return skill

    @staticmethod
    def strategy_label(strategy: LoadStrategy) -> str:
        return strategy.value
