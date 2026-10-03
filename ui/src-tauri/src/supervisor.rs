//! Starts the Python core, keeps it alive, and stops it cleanly.
//!
//! The core is `python -m wizard --headless --exit-on-stdin-close`. It prints
//! `WIZARD_READY {"port":..,"pid":..}` once its WebSocket listens; the windows
//! are then told where to connect (`core://ready`).
//!
//! Stopping is cooperative: we hold the core's stdin open and never write to
//! it, and closing it is the signal to quit. That also covers our own crash,
//! since Windows closes the pipe for us. Only if the core does not leave in
//! time is it killed, and then only the core itself: processes it launched for
//! the user (an editor from the launcher) must outlive the wizard, as they do
//! today, which rules out a kill-on-close job object.

use std::io::{BufRead, BufReader};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

const READY_PREFIX: &str = "WIZARD_READY ";
/// The core's exit code when another instance holds the lock: restarting
/// would only fail again.
const EXIT_ALREADY_RUNNING: i32 = 3;
/// More crashes than this within `CRASH_WINDOW` and we stop trying.
const MAX_CRASHES: usize = 5;
const CRASH_WINDOW: Duration = Duration::from_secs(60);
/// Closing the Claude Code connection alone takes about 5 s (measured), so
/// a shorter grace would kill a core that was quitting properly.
const STOP_GRACE: Duration = Duration::from_secs(10);

/// Where the windows connect, and the secret they must present.
#[derive(Clone, Serialize)]
pub struct Endpoint {
    pub port: u16,
    pub token: String,
}

#[derive(Clone, Serialize)]
struct Down {
    code: Option<i32>,
    restarting: bool,
    reason: String,
}

#[derive(Default)]
struct Inner {
    endpoint: Option<Endpoint>,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    /// The real interpreter's pid, from the ready line. The venv's
    /// python.exe is only a launcher that starts it as a child.
    core_pid: Option<u32>,
    stopping: bool,
    crashes: Vec<Instant>,
}

pub struct Supervisor {
    token: String,
    inner: Arc<Mutex<Inner>>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            token: new_token(),
            inner: Arc::default(),
        }
    }

    pub fn endpoint(&self) -> Option<Endpoint> {
        self.inner.lock().unwrap().endpoint.clone()
    }
}

/// One random token per run of the app, shared by every restart of the core.
fn new_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the system random source failed");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// The command that starts the core.
///
/// `WIZARD_CORE` overrides it (a path to python.exe, or to the packaged core
/// from phase M7). Otherwise, the repository's virtualenv: this file sits in
/// <repo>/ui/src-tauri, so the venv is two levels up.
fn core_command() -> Command {
    let mut command = match std::env::var_os("WIZARD_CORE") {
        Some(program) => Command::new(program),
        None => {
            // Parents, not "..": the venv's python.exe compares its own path
            // with the venv's and warns when they differ only by a "..".
            let manifest = std::path::Path::new(env!("CARGO_MANIFEST_DIR"));
            let repo = manifest
                .parent()
                .and_then(|ui| ui.parent())
                .unwrap_or(manifest);
            Command::new(repo.join(".venv").join("Scripts").join("python.exe"))
        }
    };
    command.args(["-m", "wizard", "--headless", "--exit-on-stdin-close"]);
    command
}

pub fn start(app: AppHandle) {
    let supervisor = app.state::<Supervisor>();
    let token = supervisor.token.clone();
    let inner = supervisor.inner.clone();
    spawn_core(app, token, inner);
}

fn spawn_core(app: AppHandle, token: String, inner: Arc<Mutex<Inner>>) {
    let mut command = core_command();
    command
        .env("WIZARD_UI_TOKEN", &token)
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let spawned_at = Instant::now();
    eprintln!("[supervisor] starting the core");
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            let _ = app.emit(
                "core://down",
                Down {
                    code: None,
                    restarting: false,
                    reason: format!("cannot start the core: {error}"),
                },
            );
            eprintln!("[supervisor] cannot start the core: {error}");
            return;
        }
    };
    let stdout = child.stdout.take().expect("stdout is piped");
    {
        let mut state = inner.lock().unwrap();
        state.stdin = child.stdin.take();
        state.child = Some(child);
        state.endpoint = None;
        state.core_pid = None;
    }

    // Reads the ready line, then keeps draining stdout so the core never
    // blocks on a full pipe.
    {
        let app = app.clone();
        let token = token.clone();
        let inner = inner.clone();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let Ok(line) = line else { break };
                let Some(json) = line.strip_prefix(READY_PREFIX) else {
                    continue;
                };
                let Ok(ready) = serde_json::from_str::<serde_json::Value>(json) else {
                    continue;
                };
                let Some(port) = ready["port"].as_u64().and_then(|p| u16::try_from(p).ok()) else {
                    continue;
                };
                let endpoint = Endpoint {
                    port,
                    token: token.clone(),
                };
                {
                    let mut state = inner.lock().unwrap();
                    state.endpoint = Some(endpoint.clone());
                    state.core_pid = ready["pid"].as_u64().map(|p| p as u32);
                }
                eprintln!(
                    "[supervisor] core ready on port {port} after {:.1} s",
                    spawned_at.elapsed().as_secs_f64()
                );
                let _ = app.emit("core://ready", endpoint);
            }
        });
    }

    // Watches for the exit, and decides whether to start again.
    thread::spawn(move || {
        let code = loop {
            let status = {
                let mut state = inner.lock().unwrap();
                match state.child.as_mut().map(|c| c.try_wait()) {
                    Some(Ok(Some(status))) => Some(status.code()),
                    Some(Ok(None)) => None,
                    // No child (stop() took it) or an error: treat as gone.
                    _ => Some(None),
                }
            };
            if let Some(code) = status {
                break code;
            }
            thread::sleep(Duration::from_millis(250));
        };

        let (restarting, reason, delay) = {
            let mut state = inner.lock().unwrap();
            state.child = None;
            state.stdin = None;
            state.endpoint = None;
            state.core_pid = None;
            if state.stopping {
                (false, "stopped".to_string(), Duration::ZERO)
            } else if code == Some(EXIT_ALREADY_RUNNING) {
                (
                    false,
                    "Little Wizard is already running".to_string(),
                    Duration::ZERO,
                )
            } else {
                let now = Instant::now();
                state
                    .crashes
                    .retain(|t| now.duration_since(*t) < CRASH_WINDOW);
                state.crashes.push(now);
                let count = state.crashes.len();
                if count > MAX_CRASHES {
                    (
                        false,
                        format!("the core stopped {count} times in a minute"),
                        Duration::ZERO,
                    )
                } else {
                    // 1, 2, 4, 8, 16 s: a core failing at startup is not hammered.
                    let delay = Duration::from_secs(1 << (count - 1).min(4));
                    (true, format!("the core exited ({code:?})"), delay)
                }
            }
        };
        eprintln!("[supervisor] core exited with {code:?}: {reason}");
        let _ = app.emit(
            "core://down",
            Down {
                code,
                restarting,
                reason,
            },
        );
        if restarting {
            thread::sleep(delay);
            if !inner.lock().unwrap().stopping {
                spawn_core(app, token, inner);
            }
        }
    });
}

/// Restart on request (tray menu): the crash counter does not apply.
pub fn restart(app: &AppHandle) {
    let supervisor = app.state::<Supervisor>();
    let mut state = supervisor.inner.lock().unwrap();
    state.crashes.clear();
    if state.child.is_some() {
        // Closing stdin makes the core quit; the watcher starts it again a
        // second later, as after a crash, but with the counter reset.
        state.stdin = None;
    } else {
        // It had been given up on (or never started): start it now.
        drop(state);
        start(app.clone());
    }
}

/// Ask the core to quit, wait for it, and kill it only if it hangs.
pub fn stop(app: &AppHandle) {
    let supervisor = app.state::<Supervisor>();
    let started = Instant::now();
    {
        let mut state = supervisor.inner.lock().unwrap();
        state.stopping = true;
        state.stdin = None; // the signal
    }
    loop {
        {
            let mut state = supervisor.inner.lock().unwrap();
            let gone = match state.child.as_mut() {
                None => true,
                Some(child) => !matches!(child.try_wait(), Ok(None)),
            };
            if gone {
                return;
            }
            if started.elapsed() >= STOP_GRACE {
                eprintln!("[supervisor] the core did not quit in time: killing it");
                if let Some(pid) = state.core_pid {
                    kill_pid(pid);
                }
                if let Some(child) = state.child.as_mut() {
                    let _ = child.kill();
                }
                return;
            }
        }
        thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(windows)]
fn kill_pid(pid: u32) {
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};
    unsafe {
        let handle = OpenProcess(PROCESS_TERMINATE, 0, pid);
        if !handle.is_null() {
            TerminateProcess(handle, 1);
            CloseHandle(handle);
        }
    }
}

#[cfg(not(windows))]
fn kill_pid(_pid: u32) {}

/// For the windows: where the core is, if it is up.
#[tauri::command]
pub fn core_endpoint(supervisor: tauri::State<'_, Supervisor>) -> Option<Endpoint> {
    supervisor.endpoint()
}
