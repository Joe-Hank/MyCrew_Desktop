use crate::sidecar::SidecarState;

#[tauri::command]
pub fn get_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
pub async fn get_backend_port(state: tauri::State<'_, SidecarState>) -> Result<u16, String> {
    state.port().await.ok_or_else(|| "backend not ready".into())
}
