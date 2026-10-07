//! Keep our windows out of other people's screen shares.
//!
//! The Qt UI could not do this for its translucent windows: Windows refused
//! `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` on layered windows
//! (error 8). WebView2 windows draw transparency differently, so it is tried
//! on every window and the outcome is reported, to be measured (PLAN.md, M2).
//!
//! Our own screenshots do not rely on this: the core's cloak hides every
//! window before a grab, whatever this returns.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, Manager, WebviewWindow};

/// `ui.exclude_from_capture` (config.toml), told by the core on connect and
/// after each reload. On until told otherwise: the safe side.
static EXCLUDE: AtomicBool = AtomicBool::new(true);

/// Apply the current setting to one window (every window calls this once
/// created, so one made later follows the setting too).
#[cfg(windows)]
pub fn apply(window: &WebviewWindow) {
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE, WDA_NONE,
    };

    let exclude = EXCLUDE.load(Ordering::SeqCst);
    let Ok(hwnd) = window.hwnd() else { return };
    let affinity = if exclude {
        WDA_EXCLUDEFROMCAPTURE
    } else {
        WDA_NONE
    };
    let ok = unsafe { SetWindowDisplayAffinity(hwnd.0 as _, affinity) } != 0;
    let error = if ok { 0 } else { unsafe { GetLastError() } };
    eprintln!(
        "[protect] {}: {} {}",
        window.label(),
        if exclude {
            "exclude from capture"
        } else {
            "visible to capture"
        },
        if ok {
            "ok".to_string()
        } else {
            format!("refused (error {error})")
        }
    );
}

#[cfg(not(windows))]
pub fn apply(_window: &WebviewWindow) {}

/// The setting changed: every window, now and later.
pub fn set(app: &AppHandle, exclude: bool) {
    if EXCLUDE.swap(exclude, Ordering::SeqCst) == exclude {
        return;
    }
    for window in app.webview_windows().values() {
        apply(window);
    }
}

#[tauri::command]
pub fn capture_exclusion(app: AppHandle, exclude: bool) {
    set(&app, exclude);
}
