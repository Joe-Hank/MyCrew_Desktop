use std::sync::Arc;
use std::time::Duration;

use tauri::async_runtime;
use tokio::sync::{Mutex, Notify};
use tracing::{error, info, warn};

const MAX_RESTART_ATTEMPTS: u32 = 3;
const HEALTH_CHECK_INTERVAL: Duration = Duration::from_secs(5);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Clone)]
pub struct SidecarState {
    inner: Arc<Mutex<SidecarInner>>,
    shutdown: Arc<Notify>,
}

struct SidecarInner {
    port: Option<u16>,
    pid: Option<u32>,
    restart_count: u32,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(SidecarInner {
                port: None,
                pid: None,
                restart_count: 0,
            })),
            shutdown: Arc::new(Notify::new()),
        }
    }

    pub async fn port(&self) -> Option<u16> {
        self.inner.lock().await.port
    }

    pub fn signal_shutdown(&self) {
        self.shutdown.notify_waiters();
    }
}

pub fn spawn_sidecar(state: SidecarState) {
    async_runtime::spawn(async move {
        loop {
            let attempt = {
                let inner = state.inner.lock().await;
                inner.restart_count
            };

            if attempt >= MAX_RESTART_ATTEMPTS {
                error!(attempts = MAX_RESTART_ATTEMPTS, "sidecar.max_restarts_exceeded");
                break;
            }

            if attempt > 0 {
                let delay = Duration::from_secs(2u64.pow(attempt));
                warn!(attempt, delay_secs = delay.as_secs(), "sidecar.restarting");
                tokio::time::sleep(delay).await;
            }

            info!(attempt, "sidecar.spawning");

            match do_spawn(&state).await {
                Ok(()) => {
                    info!("sidecar.exited_cleanly");
                    break;
                }
                Err(e) => {
                    error!(error = %e, attempt, "sidecar.crashed");
                    let mut inner = state.inner.lock().await;
                    inner.restart_count += 1;
                    inner.port = None;
                    inner.pid = None;
                }
            }
        }
    });
}

async fn do_spawn(state: &SidecarState) -> Result<(), String> {
    let is_dev = std::env::var("MYCREW_DEV").unwrap_or_default() == "1";

    let mut cmd = if is_dev {
        let mut c = tokio::process::Command::new("python");
        c.args(["-m", "bootstrap.main"]);
        c.current_dir(get_backend_dir());
        c
    } else {
        let exe = get_sidecar_exe();
        let mut c = tokio::process::Command::new(&exe);
        c.current_dir(exe.parent().unwrap_or_else(|| std::path::Path::new(".")));
        c
    };

    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("spawn failed: {e}"))?;
    let pid = child.id().unwrap_or(0);

    {
        let mut inner = state.inner.lock().await;
        inner.pid = Some(pid);
    }

    info!(pid, "sidecar.process_started");

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let port = wait_for_port(stdout).await?;

    {
        let mut inner = state.inner.lock().await;
        inner.port = Some(port);
        inner.restart_count = 0;
    }

    info!(port, "sidecar.port_detected");

    wait_for_health(port).await?;
    info!(port, "sidecar.healthy");

    let shutdown = state.shutdown.clone();
    tokio::select! {
        status = child.wait() => {
            match status {
                Ok(s) if s.success() => Ok(()),
                Ok(s) => Err(format!("exited with code: {}", s.code().unwrap_or(-1))),
                Err(e) => Err(format!("wait error: {e}")),
            }
        }
        _ = shutdown.notified() => {
            info!(pid, "sidecar.shutdown_requested");
            graceful_stop(port, &mut child).await;
            Ok(())
        }
    }
}

async fn wait_for_port(stdout: tokio::process::ChildStdout) -> Result<u16, String> {
    use tokio::io::{AsyncBufReadExt, BufReader};

    let reader = BufReader::new(stdout);
    let mut lines = reader.lines();
    let deadline = tokio::time::Instant::now() + STARTUP_TIMEOUT;

    loop {
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        if remaining.is_zero() {
            return Err("timeout waiting for MYCREW_PORT".into());
        }

        match tokio::time::timeout(remaining, lines.next_line()).await {
            Ok(Ok(Some(line))) => {
                info!(line = %line, "sidecar.stdout");
                if let Some(port_str) = line.strip_prefix("MYCREW_PORT=") {
                    let port: u16 = port_str
                        .trim()
                        .parse()
                        .map_err(|_| format!("invalid port: {port_str}"))?;
                    return Ok(port);
                }
            }
            Ok(Ok(None)) => return Err("stdout closed before port detected".into()),
            Ok(Err(e)) => return Err(format!("read error: {e}")),
            Err(_) => return Err("timeout waiting for MYCREW_PORT".into()),
        }
    }
}

async fn wait_for_health(port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/api/v1/health");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(3))
        .build()
        .map_err(|e| format!("http client: {e}"))?;

    for i in 0..10 {
        tokio::time::sleep(Duration::from_millis(500)).await;
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            Ok(resp) => {
                warn!(status = %resp.status(), attempt = i, "sidecar.health_not_ok");
            }
            Err(e) => {
                if i > 5 {
                    warn!(error = %e, attempt = i, "sidecar.health_unreachable");
                }
            }
        }
    }
    Err("health check failed after 10 attempts".into())
}

async fn graceful_stop(port: u16, child: &mut tokio::process::Child) {
    let url = format!("http://127.0.0.1:{port}/api/v1/lifecycle/shutdown");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .ok();

    if let Some(c) = client {
        let _ = c.post(&url).send().await;
    }

    match tokio::time::timeout(Duration::from_secs(10), child.wait()).await {
        Ok(_) => info!("sidecar.stopped_gracefully"),
        Err(_) => {
            warn!("sidecar.force_kill");
            let _ = child.kill().await;
        }
    }
}

fn get_backend_dir() -> std::path::PathBuf {
    std::env::current_dir()
        .unwrap_or_default()
        .join("backend")
}

fn get_sidecar_exe() -> std::path::PathBuf {
    let exe_dir = std::env::current_exe()
        .unwrap_or_default()
        .parent()
        .unwrap_or_else(|| std::path::Path::new("."))
        .to_path_buf();
    exe_dir.join("mycrew-backend.exe")
}

pub fn start_health_monitor(state: SidecarState) {
    async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_secs(10)).await;

        loop {
            let port = state.port().await;
            if let Some(p) = port {
                let url = format!("http://127.0.0.1:{p}/api/v1/health");
                let client = reqwest::Client::builder()
                    .timeout(Duration::from_secs(3))
                    .build();

                if let Ok(c) = client {
                    if let Err(e) = c.get(&url).send().await {
                        warn!(error = %e, "sidecar.health_monitor_failed");
                    }
                }
            }

            tokio::time::sleep(HEALTH_CHECK_INTERVAL).await;
        }
    });
}
