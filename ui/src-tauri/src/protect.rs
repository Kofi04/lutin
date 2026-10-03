//! Keep our windows out of other people's screen shares.
//!
//! The Qt UI could not do this for its translucent windows: Windows refused
//! `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` on layered windows
//! (error 8). WebView2 windows draw transparency differently, so it is tried
//! on every window and the outcome is reported, to be measured (PLAN.md, M2).
//!
//! Our own screenshots do not rely on this: the core's cloak hides every
//! window before a grab, whatever this returns.

use tauri::WebviewWindow;

#[cfg(windows)]
pub fn apply(window: &WebviewWindow) {
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        SetWindowDisplayAffinity, WDA_EXCLUDEFROMCAPTURE,
    };

    let Ok(hwnd) = window.hwnd() else { return };
    let ok = unsafe { SetWindowDisplayAffinity(hwnd.0 as _, WDA_EXCLUDEFROMCAPTURE) } != 0;
    let error = if ok { 0 } else { unsafe { GetLastError() } };
    eprintln!(
        "[protect] {}: exclude from capture {}",
        window.label(),
        if ok {
            "ok".to_string()
        } else {
            format!("refused (error {error})")
        }
    );
}

#[cfg(not(windows))]
pub fn apply(_window: &WebviewWindow) {}
