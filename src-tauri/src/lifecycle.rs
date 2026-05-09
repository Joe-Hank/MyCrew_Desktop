use tauri::{AppHandle, Manager};
use tracing::{info, warn};

use crate::sidecar::SidecarState;

pub fn setup_close_handler(app: &AppHandle) {
    let handle = app.clone();

    if let Some(window) = app.webview_windows().values().next().cloned() {
        window.on_window_event(move |event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state: tauri::State<'_, SidecarState> = handle.state();
                let port = tauri::async_runtime::block_on(state.port());

                if let Some(p) = port {
                    info!(port = p, "lifecycle.close_requested");

                    let client = reqwest::blocking::Client::builder()
                        .timeout(std::time::Duration::from_secs(3))
                        .build();

                    if let Ok(c) = client {
                        let url = format!("http://127.0.0.1:{p}/api/v1/lifecycle/state");
                        match c.get(&url).send() {
                            Ok(resp) => {
                                if let Ok(body) = resp.json::<serde_json::Value>() {
                                    let running = body["data"]["running_projects"]
                                        .as_i64()
                                        .unwrap_or(0);
                                    if running > 0 {
                                        info!(running, "lifecycle.projects_running_on_close");
                                    }
                                }
                            }
                            Err(e) => {
                                warn!(error = %e, "lifecycle.state_check_failed");
                            }
                        }
                    }
                }

                state.signal_shutdown();
                info!("lifecycle.shutdown_signaled");
            }
        });
    }
}
