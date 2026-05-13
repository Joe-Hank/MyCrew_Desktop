"""ComfyUI MCP tool bridges.

Targets the `artokun/comfyui-mcp` server (33 tools). We bridge the 8
that matter most for an LLM agent producing images:

  - comfy_create_workflow_from_template  ← create_workflow (renamed to
    avoid collision with the Plan Maker's own create_workflow)
  - comfy_validate_workflow              ← validate_workflow
  - comfy_enqueue_workflow               ← enqueue_workflow
  - comfy_get_job_status                 ← get_job_status
  - comfy_get_history                    ← get_history
  - comfy_list_local_models              ← list_local_models
  - comfy_list_output_images             ← list_output_images
  - comfy_upload_image                   ← upload_image (for img2img)

Typical flow:
  1. comfy_create_workflow_from_template(template="txt2img",
        params={positive_prompt, negative_prompt, checkpoint, ...})
  2. comfy_validate_workflow(workflow=...)
  3. comfy_enqueue_workflow(workflow=...) → prompt_id
  4. comfy_get_job_status(prompt_id) until done
  5. comfy_get_history(prompt_id) → output filenames
"""
from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from src.tools.builtin._base import GuardedMCPTool


_SERVER = "comfyui"


# ── Workflow construction ──────────────────────────────────────────

class CreateWorkflowFromTemplateArgs(BaseModel):
    template: str = Field(
        ...,
        description='One of "txt2img", "img2img", "upscale", "inpaint".',
    )
    params: dict = Field(
        default_factory=dict,
        description=(
            "Template parameters. Common keys: positive_prompt, "
            "negative_prompt, checkpoint, width, height, steps, cfg, "
            "seed, sampler_name, scheduler. For img2img/inpaint add "
            "image_path / mask_path. Defaults are filled in by ComfyUI."
        ),
    )


class ComfyCreateWorkflowFromTemplate(GuardedMCPTool):
    name: str = "comfy_create_workflow_from_template"
    description: str = (
        "Build a ComfyUI workflow JSON from a named template (txt2img / "
        "img2img / upscale / inpaint) with parameters. Returns a "
        "workflow object you can pass to comfy_validate_workflow and "
        "then comfy_enqueue_workflow."
    )
    args_schema: type[BaseModel] = CreateWorkflowFromTemplateArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "create_workflow"

    def _run(self, template: str, params: dict | None = None) -> str:
        return self._guarded_call({"template": template, "params": params or {}})


class ValidateWorkflowArgs(BaseModel):
    workflow: Any = Field(..., description="ComfyUI workflow (object or JSON string).")


class ComfyValidateWorkflow(GuardedMCPTool):
    name: str = "comfy_validate_workflow"
    description: str = (
        "Validate a ComfyUI workflow before submitting — checks for missing "
        "models, broken connections, invalid node references. Returns "
        "errors + warnings; do not enqueue if errors are present."
    )
    args_schema: type[BaseModel] = ValidateWorkflowArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "validate_workflow"

    def _run(self, workflow: Any) -> str:
        return self._guarded_call({"workflow": workflow})


# ── Submission / status ────────────────────────────────────────────

class EnqueueWorkflowArgs(BaseModel):
    workflow: Any = Field(..., description="ComfyUI workflow in API format.")
    disable_random_seed: bool = Field(
        False,
        description="Set True to keep the seed deterministic across calls.",
    )


class ComfyEnqueueWorkflow(GuardedMCPTool):
    name: str = "comfy_enqueue_workflow"
    description: str = (
        "Submit a ComfyUI workflow for execution. Returns immediately "
        "with a prompt_id and queue position — does NOT wait. Use "
        "comfy_get_job_status to poll, then comfy_get_history to fetch "
        "the produced filenames."
    )
    args_schema: type[BaseModel] = EnqueueWorkflowArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "enqueue_workflow"
    permission_kind: ClassVar[str | None] = "cmd_exec"

    def _run(self, workflow: Any, disable_random_seed: bool = False) -> str:
        return self._guarded_call({
            "workflow": workflow,
            "disable_random_seed": disable_random_seed,
        })


class JobStatusArgs(BaseModel):
    prompt_id: str = Field(..., description="The prompt_id returned by comfy_enqueue_workflow.")


class ComfyGetJobStatus(GuardedMCPTool):
    name: str = "comfy_get_job_status"
    description: str = "Check whether a queued ComfyUI job has finished. Returns its current state."
    args_schema: type[BaseModel] = JobStatusArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_job_status"

    def _run(self, prompt_id: str) -> str:
        return self._guarded_call({"prompt_id": prompt_id})


class GetHistoryArgs(BaseModel):
    prompt_id: str | None = Field(
        None,
        description="Specific prompt_id; omit to fetch the most recent execution.",
    )


class ComfyGetHistory(GuardedMCPTool):
    name: str = "comfy_get_history"
    description: str = (
        "Retrieve the full execution history for a ComfyUI prompt — "
        "output filenames, timing, error details with tracebacks. Call "
        "after a job completes (or fails) to get its results."
    )
    args_schema: type[BaseModel] = GetHistoryArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "get_history"

    def _run(self, prompt_id: str | None = None) -> str:
        args: dict = {}
        if prompt_id:
            args["prompt_id"] = prompt_id
        return self._guarded_call(args)


# ── Inventory ──────────────────────────────────────────────────────

class ListLocalModelsArgs(BaseModel):
    model_type: str | None = Field(
        None,
        description='Filter: "checkpoints" / "loras" / "vae" / "controlnet" etc. Omit to list all.',
    )


class ComfyListLocalModels(GuardedMCPTool):
    name: str = "comfy_list_local_models"
    description: str = "List models installed in the local ComfyUI models/ directory. Use this to pick a valid checkpoint name before building a workflow."
    args_schema: type[BaseModel] = ListLocalModelsArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "list_local_models"

    def _run(self, model_type: str | None = None) -> str:
        args: dict = {}
        if model_type:
            args["model_type"] = model_type
        return self._guarded_call(args)


class ListOutputImagesArgs(BaseModel):
    limit: int = Field(20, description="Max images (1-100, default 20).")
    pattern: str | None = Field(None, description="Optional case-insensitive substring filter on filename.")


class ComfyListOutputImages(GuardedMCPTool):
    name: str = "comfy_list_output_images"
    description: str = "List recently generated images in the ComfyUI output/ directory (newest first)."
    args_schema: type[BaseModel] = ListOutputImagesArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "list_output_images"
    permission_kind: ClassVar[str | None] = "folder_read"

    def _run(self, limit: int = 20, pattern: str | None = None) -> str:
        args: dict = {"limit": limit}
        if pattern:
            args["pattern"] = pattern
        return self._guarded_call(args)


# ── img2img support ────────────────────────────────────────────────

class UploadImageArgs(BaseModel):
    source_path: str = Field(..., description="Absolute path to a local image to upload into ComfyUI's input/ dir.")
    filename: str | None = Field(None, description="Override filename inside ComfyUI; auto-detected otherwise.")


class ComfyUploadImage(GuardedMCPTool):
    name: str = "comfy_upload_image"
    description: str = "Copy a local image into ComfyUI's input/ directory so img2img/inpaint workflows can reference it via LoadImage."
    args_schema: type[BaseModel] = UploadImageArgs
    mcp_server_id: ClassVar[str] = _SERVER
    mcp_tool_name: ClassVar[str] = "upload_image"
    permission_kind: ClassVar[str | None] = "file_write"

    def _run(self, source_path: str, filename: str | None = None) -> str:
        args: dict = {"source_path": source_path}
        if filename:
            args["filename"] = filename
        return self._guarded_call(args)


__all__ = [
    "ComfyCreateWorkflowFromTemplate",
    "ComfyValidateWorkflow",
    "ComfyEnqueueWorkflow",
    "ComfyGetJobStatus",
    "ComfyGetHistory",
    "ComfyListLocalModels",
    "ComfyListOutputImages",
    "ComfyUploadImage",
]
