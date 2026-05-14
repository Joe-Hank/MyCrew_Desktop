mod commands;
mod lifecycle;
mod sidecar;

use tauri::Manager;

pub fn run() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "mycrew=info".into()),
        )
        .init();

    let sidecar_state = sidecar::SidecarState::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.webview_windows().values().next() {
                let _ = w.set_focus();
            }
        }))
        .manage(sidecar_state.clone())
        .setup(move |app| {
            let handle = app.handle().clone();

            sidecar::spawn_sidecar(sidecar_state.clone());
            sidecar::start_health_monitor(sidecar_state);
            lifecycle::setup_close_handler(&handle);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_version,
            commands::get_backend_port,
        ])
        .run(tauri::generate_context!())
        .expect("error while running MyCrew");
}
