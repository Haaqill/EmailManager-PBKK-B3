"""Tulis JSON Schema PlanSnapshot ke contracts/plan-schema.json (root repo).

Jalankan dari gmail-agent/:  python export_plan_schema.py
Tes tests/test_plan_contract.py gagal bila file ini belum diekspor ulang setelah
skema di app/privacy/contract.py berubah.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.privacy.contract import PlanSnapshot

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "contracts" / "plan-schema.json"


def render_schema() -> str:
    return json.dumps(PlanSnapshot.model_json_schema(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(render_schema(), encoding="utf-8", newline="\n")
    print(f"Skema ditulis ke {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
