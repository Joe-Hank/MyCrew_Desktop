"""Unity MCP: manage_probuilder — ProBuilder 网格操作."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManageProBuilderArgs(BaseModel):
    """manage_probuilder 参数."""
    action: str = Field(
        ...,
        description=(
            "Action 分组:\n"
            "  Shape: create_shape, create_poly_shape\n"
            "  Mesh Edit: extrude_faces, extrude_edges, bevel_edges, subdivide, delete_faces, "
            "bridge_edges, connect_elements, detach_faces, flip_normals, merge_faces, "
            "combine_meshes, merge_objects, duplicate_and_flip, create_polygon\n"
            "  Vertex: merge_vertices, weld_vertices, split_vertices, move_vertices, "
            "insert_vertex, append_vertices_to_edge\n"
            "  Selection: select_faces\n"
            "  UV & Materials: set_face_material, set_face_color, set_face_uvs\n"
            "  Query: get_mesh_info, ping\n"
            "  Smoothing: set_smoothing, auto_smooth\n"
            "  Utilities: center_pivot, freeze_transform, validate_mesh, repair_mesh"
        ),
    )
    target: str | None = Field(default=None, description="目标 GameObject 名称/路径/ID")
    search_method: str | None = Field(default=None, description="查找方式: by_id, by_name, by_path, by_tag, by_layer")
    properties: dict | str | None = Field(
        default=None,
        description=(
            "Action 特定参数字典。常用 keys:\n"
            "  create_shape: shape_type(Cube/Cylinder/Sphere/Plane/Cone/Torus/Pipe/Arch/Stair/...), "
            "size, position, rotation, name\n"
            "  extrude_faces: faceIndices, distance, method\n"
            "  bevel_edges: edgeIndices/edges, amount\n"
            "  get_mesh_info: include('summary'|'faces'|'edges'|'all')\n"
            "  select_faces: direction, tolerance / growFrom, growAngle\n"
            "  set_face_material: faceIndices, materialPath\n"
            "  set_face_color: faceIndices, color [r,g,b,a]\n"
            "  set_face_uvs: faceIndices, scale, offset, rotation\n"
            "  auto_smooth: angleThreshold\n"
            "  weld_vertices: vertexIndices, radius\n"
            "  move_vertices: vertexIndices, offset [x,y,z]"
        ),
    )


def _run_manage_probuilder(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_probuilder", args)


manage_probuilder_tool = CrewStructuredTool.from_function(
    name="manage_probuilder",
    description=(
        "ProBuilder 网格操作：创建形状、挤出/倒角/细分面和边、顶点操作、UV/材质设置、"
        "网格查询/验证/修复。需要 com.unity.probuilder 包。"
    ),
    func=_run_manage_probuilder,
    args_schema=ManageProBuilderArgs,
)

__all__ = ["ManageProBuilderArgs", "manage_probuilder_tool"]
