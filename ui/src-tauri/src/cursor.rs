//! Where the pointer is, for the avatar's eyes, at almost no cost.
//!
//! The avatar used to ask for the cursor six times a second, a round trip to
//! Rust each time: measured at about 6 % of a core with the WebView work it
//! caused. Here a thread reads the cursor itself (a cheap system call, no
//! message to the page) and tells the avatar only when it has moved, and only
//! while the avatar is on screen. A still mouse costs nothing.
//!
//! The guide cursor (DESIGN.md section 6) follows the pointer more closely,
//! but only while an overlay asks for it (`cursor_listen`): at rest nothing
//! is sent to the overlays at all.

use std::collections::HashSet;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager};

use crate::windows::{AVATAR, OVERLAY_PREFIX};

const PERIOD: Duration = Duration::from_millis(120);
/// While the guide follows the pointer: 60 Hz, a display's own rate, so the
/// companion cursor moves with the real one. Still only while an overlay
/// listens, and only when the pointer moved: a still mouse sends nothing.
const GUIDE_PERIOD: Duration = Duration::from_millis(16);
const GUIDE_MIN_MOVE: i32 = 3;

/// The overlays showing the guide, which want the pointer. A set, not a
/// flag: with two screens, one overlay stopping must not cut the other off.
static GUIDE_LISTENERS: Mutex<Option<HashSet<String>>> = Mutex::new(None);

fn guiding() -> bool {
    GUIDE_LISTENERS
        .lock()
        .unwrap()
        .as_ref()
        .is_some_and(|set| !set.is_empty())
}
/// Smaller moves are not worth waking the page for: the eyes look in one of
/// 16 directions (pose.ts), which a few pixels never change.
const MIN_MOVE: i32 = 12;

#[derive(Clone, Copy, Serialize, PartialEq, Debug)]
pub struct Cursor {
    pub x: i32,
    pub y: i32,
}

/// True when the pointer moved far enough to be worth telling.
fn moved(last: Option<Cursor>, now: Cursor) -> bool {
    moved_by(last, now, MIN_MOVE)
}

fn moved_by(last: Option<Cursor>, now: Cursor, step: i32) -> bool {
    match last {
        None => true,
        Some(last) => (now.x - last.x).abs() >= step || (now.y - last.y).abs() >= step,
    }
}

#[cfg(windows)]
fn read() -> Option<Cursor> {
    use windows_sys::Win32::Foundation::POINT;
    use windows_sys::Win32::UI::WindowsAndMessaging::GetCursorPos;
    let mut point = POINT { x: 0, y: 0 };
    // Physical pixels, the same space as the window positions.
    (unsafe { GetCursorPos(&mut point) } != 0).then_some(Cursor {
        x: point.x,
        y: point.y,
    })
}

#[cfg(not(windows))]
fn read() -> Option<Cursor> {
    None
}

pub fn start(app: AppHandle) {
    thread::spawn(move || {
        let mut last = None;
        let mut last_guide = None;
        // Debug builds report how many moves reached the page, to tell an
        // idle measurement from one taken while the mouse was in use.
        let mut told = 0u32;
        let mut since = Instant::now();
        loop {
            if cfg!(debug_assertions) && since.elapsed() >= Duration::from_secs(30) {
                eprintln!("[cursor] {told} moves told in the last 30 s");
                told = 0;
                since = Instant::now();
            }
            let guiding = guiding();
            thread::sleep(if guiding { GUIDE_PERIOD } else { PERIOD });
            // The cursor first: reading it is a system call, while asking
            // whether the avatar is visible wakes the app's main loop. A still
            // mouse must cost nothing (measured: 0.5 % of a core otherwise).
            let Some(now) = read() else { continue };
            if guiding && moved_by(last_guide, now, GUIDE_MIN_MOVE) {
                last_guide = Some(now);
                for (label, _) in app.webview_windows() {
                    if label.starts_with(OVERLAY_PREFIX) {
                        let _ = app.emit_to(label.as_str(), "cursor://moved", now);
                    }
                }
            } else if !guiding {
                last_guide = None;
            }
            if !moved(last, now) {
                continue;
            }
            let Some(avatar) = app.get_webview_window(AVATAR) else {
                continue;
            };
            if !avatar.is_visible().unwrap_or(false) {
                continue; // `last` kept as is: the next move is told once shown
            }
            last = Some(now);
            let _ = app.emit_to(AVATAR, "cursor://moved", now);
            told += 1;
        }
    });
}

/// An overlay starts or stops following the pointer.
#[tauri::command]
pub fn cursor_listen(window: tauri::WebviewWindow, listen: bool) {
    let mut listeners = GUIDE_LISTENERS.lock().unwrap();
    let set = listeners.get_or_insert_with(HashSet::new);
    if listen {
        set.insert(window.label().to_string());
    } else {
        set.remove(window.label());
    }
}

/// Where the pointer is now, physical pixels: once, when the guide appears.
#[tauri::command]
pub fn cursor_now() -> Option<Cursor> {
    read()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_first_reading_always_goes_through() {
        assert!(moved(None, Cursor { x: 0, y: 0 }));
    }

    #[test]
    fn a_still_or_trembling_mouse_says_nothing() {
        let last = Some(Cursor { x: 100, y: 100 });
        assert!(!moved(last, Cursor { x: 100, y: 100 }));
        assert!(!moved(last, Cursor { x: 111, y: 89 }));
    }

    #[test]
    fn a_real_move_is_told() {
        let last = Some(Cursor { x: 100, y: 100 });
        assert!(moved(last, Cursor { x: 112, y: 100 }));
        assert!(moved(last, Cursor { x: 100, y: 88 }));
    }
}
