from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from core.config import (
    CanonicalConfig,
    CanonicalItem,
    CanonicalNode,
    CanonicalVersionSummary,
    ConfigMeta,
    list_canonical_version_summaries,
    load_canonical_config_from_db,
    save_canonical_config,
)


def _create_config(name: str, sku: str, node_code: str) -> CanonicalConfig:
    return CanonicalConfig(
        meta=ConfigMeta(name=name, status="draft"),
        items=[CanonicalItem(code=sku)],
        nodes=[CanonicalNode(code=node_code, node_type="store", name=node_code)],
        arcs=[],
        bom=[],
        demands=[],
        capacities=[],
        calendars=[],
        hierarchies=[],
    )


def _prepare_db(db_path: Path) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = Config(str(Path("alembic.ini").resolve()))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")
    return str(db_path)


def test_save_canonical_config_persists_counts_metadata(tmp_path):
    db_path = _prepare_db(tmp_path / "canonical_counts.db")
    config = _create_config("test-counts", "SKU-CNT", "NODE-CNT")
    version_id = save_canonical_config(config, db_path=db_path)

    summaries: list[CanonicalVersionSummary] = list_canonical_version_summaries(
        limit=20, db_path=db_path
    )
    summary = next(s for s in summaries if s.meta.version_id == version_id)

    assert summary.counts["items"] == 1
    assert summary.counts["nodes"] == 1
    assert summary.counts["arcs"] == 0

    loaded, _ = load_canonical_config_from_db(
        version_id, validate=False, db_path=db_path
    )
    assert loaded.meta.attributes.get("counts", {}).get("items") == 1
