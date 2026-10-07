//! Where the avatar was left, kept across restarts (the Qt avatar's
//! state.ini did the same).
//!
//! Saved a moment after a move stops, not on every pixel of a drag. Read
//! back only if that point is still on a monitor: a screen unplugged since
//! must not leave him somewhere nobody can see.

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, PhysicalPosition, WebviewWindow, WindowEvent};

const FILE: &str = "avatar-position.json";
const SAVE_AFTER: Duration = Duration::from_millis(500);

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq)]
struct Saved {
    x: i32,
    y: i32,
}

static LATEST: Mutex<Option<Saved>> = Mutex::new(None);
static PENDING: AtomicBool = AtomicBool::new(false);
/// Where we put him ourselves (startup, "Replacer sur la barre"): that move
/// is not the user's choice and is not saved. Compared by value because the
/// Moved event arrives later, through the event loop.
static PLACED: Mutex<Option<Saved>> = Mutex::new(None);

fn path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|dir| dir.join(FILE))
}

/// The saved position, if it is still on one of the monitors.
pub fn saved(window: &WebviewWindow) -> Option<PhysicalPosition<i32>> {
    let text = fs::read_to_string(path(window.app_handle())?).ok()?;
    let saved: Saved = serde_json::from_str(&text).ok()?;
    let on_screen = window.available_monitors().ok()?.iter().any(|m| {
        let (p, s) = (m.position(), m.size());
        saved.x >= p.x
            && saved.y >= p.y
            && saved.x < p.x + s.width as i32
            && saved.y < p.y + s.height as i32
    });
    on_screen.then(|| PhysicalPosition::new(saved.x, saved.y))
}

/// Forget it: the next start (and "Replacer sur la barre") uses the corner.
pub fn forget(app: &AppHandle) {
    *LATEST.lock().unwrap() = None;
    if let Some(file) = path(app) {
        let _ = fs::remove_file(file);
    }
}

/// We are about to move him there ourselves.
pub fn placing(at: PhysicalPosition<i32>) {
    *PLACED.lock().unwrap() = Some(Saved { x: at.x, y: at.y });
}

/// Save the avatar's position whenever the user moves him.
pub fn watch(avatar: &WebviewWindow) {
    let app = avatar.app_handle().clone();
    avatar.on_window_event(move |event| {
        let WindowEvent::Moved(at) = event else {
            return;
        };
        let at = Saved { x: at.x, y: at.y };
        if *PLACED.lock().unwrap() == Some(at) {
            return;
        }
        *LATEST.lock().unwrap() = Some(at);
        if PENDING.swap(true, Ordering::SeqCst) {
            return; // a save is already on its way, with the latest point
        }
        let app = app.clone();
        thread::spawn(move || {
            thread::sleep(SAVE_AFTER);
            PENDING.store(false, Ordering::SeqCst);
            let latest = *LATEST.lock().unwrap();
            if let (Some(saved), Some(file)) = (latest, path(&app)) {
                if let Some(dir) = file.parent() {
                    let _ = fs::create_dir_all(dir);
                }
                if let Ok(text) = serde_json::to_string(&saved) {
                    let _ = fs::write(file, text);
                }
            }
        });
    });
}
