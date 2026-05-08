"""Unity MCP: manage_physics — 3D/2D 物理管理."""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field
from crewai.tools.structured_tool import CrewStructuredTool


class ManagePhysicsArgs(BaseModel):
    """manage_physics 参数."""
    action: str = Field(
        ...,
        description=(
            "Action 分组:\n"
            "  Settings: ping, get_settings, set_settings\n"
            "  Collision Matrix: get_collision_matrix, set_collision_matrix\n"
            "  Materials: create_physics_material, configure_physics_material, assign_physics_material\n"
            "  Joints: add_joint, configure_joint, remove_joint\n"
            "  Queries: raycast, raycast_all, linecast, shapecast, overlap\n"
            "  Forces: apply_force\n"
            "  Rigidbody: get_rigidbody, configure_rigidbody\n"
            "  Validation: validate\n"
            "  Simulation: simulate_step"
        ),
    )
    dimension: str | None = Field(default=None, description="物理维度: '3d' (默认) | '2d'")
    target: str | None = Field(default=None, description="目标 GameObject")
    settings: dict | None = Field(default=None, description="set_settings 的物理设置字典")
    # Collision matrix
    layer_a: str | None = Field(default=None, description="碰撞矩阵层 A")
    layer_b: str | None = Field(default=None, description="碰撞矩阵层 B")
    collide: bool | None = Field(default=None, description="set_collision_matrix 启用/禁用碰撞")
    # Physics material
    name: str | None = Field(default=None, description="物理材质名称")
    path: str | None = Field(default=None, description="资产路径")
    dynamic_friction: float | None = Field(default=None, description="动摩擦力 0-1")
    static_friction: float | None = Field(default=None, description="静摩擦力 0-1")
    bounciness: float | None = Field(default=None, description="弹性 0-1")
    friction_combine: str | None = Field(default=None, description="摩擦合并: Average, Minimum, Multiply, Maximum")
    bounce_combine: str | None = Field(default=None, description="弹性合并模式")
    material_path: str | None = Field(default=None, description="assign_physics_material 的材质路径")
    # Joints
    joint_type: str | None = Field(default=None, description="关节类型 (3D: fixed/hinge/spring/character/configurable; 2D: distance/fixed/...)")
    connected_body: str | None = Field(default=None, description="连接体 GameObject")
    motor: dict | None = Field(default=None, description="关节马达配置")
    limits: dict | None = Field(default=None, description="关节限制配置")
    spring: dict | None = Field(default=None, description="关节弹簧配置")
    drive: dict | None = Field(default=None, description="关节驱动配置")
    properties: dict | None = Field(default=None, description="configure_joint/rigidbody 属性字典")
    # Queries
    origin: list[float] | None = Field(default=None, description="射线起点 [x,y,z] 或 [x,y]")
    direction: list[float] | None = Field(default=None, description="射线方向")
    max_distance: float | None = Field(default=None, description="最大射线距离")
    shape: str | None = Field(default=None, description="overlap/shapecast 形状: sphere, box, capsule")
    position: list[float] | None = Field(default=None, description="overlap 位置")
    size: Any | None = Field(default=None, description="overlap 大小: float (半径) 或 [x,y,z] (半范围)")
    layer_mask: str | None = Field(default=None, description="层掩码")
    start: list[float] | None = Field(default=None, description="linecast 起点")
    end: list[float] | None = Field(default=None, description="linecast 终点")
    # Forces
    force: list[float] | None = Field(default=None, description="力向量 [x,y,z]")
    force_mode: str | None = Field(default=None, description="力模式: Force, Impulse, Acceleration, VelocityChange")
    force_type: str | None = Field(default=None, description="力类型: normal, explosion")
    torque: list[float] | None = Field(default=None, description="扭矩")
    explosion_position: list[float] | None = Field(default=None, description="爆炸中心")
    explosion_radius: float | None = Field(default=None, description="爆炸半径")
    explosion_force: float | None = Field(default=None, description="爆炸力")
    upwards_modifier: float | None = Field(default=None, description="爆炸 Y 轴偏移")
    # Simulation
    steps: int | None = Field(default=None, description="simulate_step 步数 (1-100)")
    step_size: float | None = Field(default=None, description="步长秒数")


def _run_manage_physics(**kwargs: Any) -> str:
    from src.tools.builtin.unity._mcp import get_unity_mcp_pool
    pool = get_unity_mcp_pool()
    args = {k: v for k, v in kwargs.items() if v is not None}
    return pool.call("unity", "manage_physics", args)


manage_physics_tool = CrewStructuredTool.from_function(
    name="manage_physics",
    description=(
        "3D/2D 物理管理：设置/碰撞矩阵/物理材质/关节/射线检测/力/刚体配置/验证/模拟步进。"
        "所有 action 支持 dimension='3d'|'2d'。"
    ),
    func=_run_manage_physics,
    args_schema=ManagePhysicsArgs,
)

__all__ = ["ManagePhysicsArgs", "manage_physics_tool"]
