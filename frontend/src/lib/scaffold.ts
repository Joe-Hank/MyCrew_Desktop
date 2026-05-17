/** Shared scaffold helpers used by ProjectCard + TaskHeader + the
 *  ScaffoldConfigModal. Single source of truth for the template ↔
 *  display label map and the slug derivation rule.
 *
 *  Keep in sync with backend/services/template_cloner_svc.py's
 *  TEMPLATE_ID_TO_DIR map. */

/** Display labels for the four shipping Unity templates. Used by the
 *  config modal header + future settings UIs. */
export const TEMPLATE_LABELS: Record<string, string> = {
  unity_universal_2d: "Universal 2D",
  unity_universal_3d: "Universal 3D",
  unity_ar_mobile: "AR Mobile",
  unity_mr_core: "MR Core",
};

/** True if the given template_id is one we can scaffold (== have a
 *  matching subdir in github.com/Joe-Hank/Templates). Non-template or
 *  legacy projects return false; those don't get a scaffold modal. */
export function isScaffoldableTemplate(templateId: string | null | undefined): boolean {
  return !!templateId && templateId in TEMPLATE_LABELS;
}

/** Best-effort slug derivation from the project's display name.
 *  - ASCII-safe names (`PacMan`, `Goldminer_2`) → used as-is, trimmed
 *    to 64 chars.
 *  - Chinese / mixed names → empty string; the user is expected to
 *    type the English equivalent in the modal.
 *  - Names whose first char isn't alphanumeric (`_foo`, `-bar`) →
 *    empty, since the backend rejects those.
 *
 *  Mirrors backend's _SAFE_NAME_RE in template_cloner_svc.py. */
export function deriveSlugFromName(name: string): string {
  const cleaned = name.replace(/[^A-Za-z0-9_-]/g, "");
  if (!cleaned) return "";
  return /^[A-Za-z0-9]/.test(cleaned) ? cleaned.slice(0, 64) : "";
}
