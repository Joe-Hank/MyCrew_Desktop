"""Manual seeder for a single-Crew ComfyUI debug project.

Creates a minimal project that has exactly ONE Crew task card on the
canvas (the 2D 美术资产组 parent) with 3 fan-out children — one per
target resolution. No setup task, no final QA, no template / scaffold.

Run with:
    python -m scripts.seed_comfyui_debug_project

Target case: Butcher (黑袍纠察队) portrait set for ComfyUI workflow
debugging:
  - Butcher_64.png    (64x64 头像)
  - Butcher_512.png   (512x512 头像)
  - Butcher_1080.png  (1080x1080 全身像)

All produce: 仅人物 + 透明背景 + PNG.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

# Repo root = parent of backend/, where data/db/mycrew.db lives.
DB = str(Path(__file__).resolve().parents[2] / "data" / "db" / "mycrew.db")
CREW_2D_ID = "crew_117e4d3b20d1"  # 2D 美术资产组
ROOT_PATH = r"E:\ComfyUIData"
PROJECT_NAME = "ComfyUI 调试 · Butcher 三张图"

CHILDREN = [
    {
        "title": "Butcher 64×64 头像",
        "output_path": "Assets/Sprites/Butcher_64.png",
        "width": 64,
        "height": 64,
        "framing": "头像（肩部以上）",
    },
    {
        "title": "Butcher 512×512 头像",
        "output_path": "Assets/Sprites/Butcher_512.png",
        "width": 512,
        "height": 512,
        "framing": "头像（肩部以上）",
    },
    {
        "title": "Butcher 1080×1080 全身像",
        "output_path": "Assets/Sprites/Butcher_1080.png",
        "width": 1080,
        "height": 1080,
        "framing": "全身像（含整个身体）",
    },
]


def _rand_id(prefix: str) -> str:
    import secrets
    return f"{prefix}_{secrets.token_hex(6)}"


def _output_schema(width: int, height: int) -> dict:
    """PM v5 contract for a single-image task."""
    return {
        "type": "object",
        "properties": {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "width": {"type": "integer", "const": width},
            "height": {"type": "integer", "const": height},
        },
        "required": ["file_paths", "width", "height"],
    }


def _child_detail(spec: dict) -> str:
    return (
        f"产出 {spec['framing']}，尺寸 {spec['width']}×{spec['height']}，"
        f"PNG 格式，**透明背景**（alpha channel）。"
        "主体：黑袍纠察队（The Boys）中的 Butcher（Billy Butcher）—— "
        "中年白人男性，深色短发后梳，浓密络腮胡子，灰色或黑色风衣，"
        "略带阴郁的表情，反英雄气质。"
        f"严禁出现背景元素 / 文字 / 水印 / 多人 / logo。"
        f"路径：{spec['output_path']}。"
    )


def _parent_detail() -> str:
    lines = [
        "本任务为 Crew v5 fan-out 容器，包含 3 个子产物，"
        "请按下方清单逐个产出（每条对应一个 output_path）：",
    ]
    for i, s in enumerate(CHILDREN, start=1):
        lines.append("")
        lines.append(f"── 子产物 {i}: {s['title']}")
        lines.append(f"   产出路径: {s['output_path']}")
        lines.append(f"   要求: {_child_detail(s)}")
    return "\n".join(lines)


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # Sanity: confirm crew exists.
    cur.execute("SELECT id FROM crews WHERE id=?", (CREW_2D_ID,))
    if not cur.fetchone():
        print(f"crew {CREW_2D_ID} not found — refusing to seed", file=sys.stderr)
        return 1

    pid = _rand_id("proj")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        """
        INSERT INTO projects (
            id, name, root_path, template_id, scaffold_status,
            state, is_running, progress_pct, execution_kind, created_at
        ) VALUES (?, ?, ?, NULL, NULL, 'ready', 0, 0, 'sequential', ?)
        """,
        (pid, PROJECT_NAME, ROOT_PATH, now),
    )
    print(f"OK project {pid} created")

    # Parent crew_group task.
    union_paths = [c["output_path"] for c in CHILDREN]
    # Parent output_schema is the loose envelope (file_paths union; width/
    # height aren't single values across 3 different resolutions, so leave
    # them off the parent — each child enforces its own).
    parent_schema = {
        "type": "object",
        "properties": {
            "file_paths": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": len(CHILDREN),
            },
        },
        "required": ["file_paths"],
    }
    parent_id = _rand_id("task")
    cur.execute(
        """
        INSERT INTO tasks (
            id, project_id, title, detail, agent_id, kind, output_schema,
            status, deps, performer_kind, performer_id, output_paths,
            parent_task_id, parent_step_index
        ) VALUES (?, ?, ?, ?, NULL, 'crew', ?, 'pending', '[]',
                  'crew', ?, ?, NULL, NULL)
        """,
        (
            parent_id, pid,
            "Butcher 三张图（64 / 512 / 1080）",
            _parent_detail(),
            json.dumps(parent_schema, ensure_ascii=False),
            CREW_2D_ID,
            json.dumps(union_paths, ensure_ascii=False),
        ),
    )
    print(f"OK parent crew task {parent_id} created")

    # Three children, each one image. parent_step_index is left NULL —
    # workflow_svc._fanout_step stamps it at dispatch time. Front-end
    # smart-default routes NULL children to the first fanout step.
    for spec in CHILDREN:
        cid = _rand_id("task")
        cur.execute(
            """
            INSERT INTO tasks (
                id, project_id, title, detail, agent_id, kind, output_schema,
                status, deps, performer_kind, performer_id, output_paths,
                parent_task_id, parent_step_index
            ) VALUES (?, ?, ?, ?, NULL, 'regular', ?, 'pending', ?,
                      'crew', ?, ?, ?, NULL)
            """,
            (
                cid, pid, spec["title"], _child_detail(spec),
                json.dumps(_output_schema(spec["width"], spec["height"]),
                           ensure_ascii=False),
                # Children depend on the parent so they only get
                # dispatched via the fan-out path, not by the top-level
                # scheduler. Matches the post-merge shape used by PM v5.
                json.dumps([parent_id], ensure_ascii=False),
                CREW_2D_ID,
                json.dumps([spec["output_path"]], ensure_ascii=False),
                parent_id,
            ),
        )
        print(f"  OK child {cid} → {spec['output_path']} ({spec['width']}×{spec['height']})")

    con.commit()
    con.close()
    print(f"\nproject_id: {pid}")
    print(f"root_path:  {ROOT_PATH}")
    print("Open the app and refresh — the new project should appear in the list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
