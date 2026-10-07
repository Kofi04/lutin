//! The windows of DESIGN.md section 2: avatar, panel, and one overlay per screen.
//!
//! Every window is created here, in Rust, rather than in tauri.conf.json:
//! their position depends on the monitors, and the overlays come and go with
//! them.

use tauri::{
    AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize, WebviewUrl,
    WebviewWindow, WebviewWindowBuilder, WindowEvent,
};

use std::sync::atomic::{AtomicU64, Ordering};

use crate::{position, protect};

pub const AVATAR: &str = "avatar";
pub const PANEL: &str = "panel";
/// The ordinary window: settings, history, notes... (DESIGN.md section 2).
pub const APP: &str = "app";

/// The views the app window can show; anything else is refused.
const APP_VIEWS: [&str; 8] = [
    "settings",
    "history",
    "clipboard",
    "notes",
    "reminders",
    "hooks",
    "onboarding",
    "agent",
];
pub const OVERLAY_PREFIX: &str = "overlay-";

/// DESIGN.md section 4: a 56 px figure in a 72 px window.
const AVATAR_SIZE: f64 = 72.0;
/// `appearance.scale` (config.toml), as f64 bits: the avatar window is
/// AVATAR_SIZE times this, and so is everything measured on it.
static AVATAR_SCALE: AtomicU64 = AtomicU64::new(0x3FF0_0000_0000_0000); // 1.0

fn avatar_scale() -> f64 {
    f64::from_bits(AVATAR_SCALE.load(Ordering::SeqCst))
}
const PANEL_WIDTH: f64 = 520.0;
const PANEL_HEIGHT: f64 = 420.0;
/// Space between the avatar and the screen edges, in logical pixels.
const MARGIN: f64 = 12.0;

/// A floating window: no frame, no shadow, no taskbar button, on top.
fn floating<'a>(
    app: &'a AppHandle,
    label: &'a str,
    url: &str,
) -> WebviewWindowBuilder<'a, tauri::Wry, AppHandle> {
    WebviewWindowBuilder::new(app, label, WebviewUrl::App(url.into()))
        .title("Little Wizard")
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .visible(false)
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    // The avatar never takes the focus: clicking him must not pull the
    // keyboard away from whatever you are typing in.
    let avatar = floating(app, AVATAR, "avatar.html")
        .inner_size(AVATAR_SIZE, AVATAR_SIZE)
        .min_inner_size(AVATAR_SIZE, AVATAR_SIZE)
        .focused(false)
        .focusable(false)
        .build()?;
    // Windows sizes a new window before tao handles its messages, so the
    // creation size is clamped to SM_CXMINTRACK (136 px here) and the avatar
    // spilled off-screen. Resized now, the minimum above applies instead.
    avatar.set_size(LogicalSize::new(AVATAR_SIZE, AVATAR_SIZE))?;
    place_avatar(&avatar)?;
    position::watch(&avatar);
    protect::apply(&avatar);
    set_visible(&avatar, true, false)?;

    let panel = floating(app, PANEL, "panel.html")
        .inner_size(PANEL_WIDTH, PANEL_HEIGHT)
        .focused(false)
        .build()?;
    protect::apply(&panel);

    sync_overlays(app)?;
    Ok(())
}

/// Where he was left (position.rs), or the default corner.
fn place_avatar(avatar: &WebviewWindow) -> tauri::Result<()> {
    match position::saved(avatar) {
        Some(at) => {
            position::placing(at);
            avatar.set_position(at)
        }
        None => snap_avatar(avatar),
    }
}

/// Bottom-right corner of the primary screen, just above the taskbar.
///
/// The work area is the screen minus the taskbar, wherever the taskbar is.
pub fn snap_avatar(avatar: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = avatar.primary_monitor()? else {
        return Ok(());
    };
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let size = ((AVATAR_SIZE * avatar_scale() + MARGIN) * scale).round() as i32;
    let x = area.position.x + area.size.width as i32 - size;
    let y = area.position.y + area.size.height as i32 - size;
    let at = PhysicalPosition::new(x, y);
    position::placing(at);
    avatar.set_position(at)
}

/// Ask the panel to open or close: its own state machine decides what that
/// means (an approval waiting is not dismissed by a click on the avatar).
pub fn toggle(app: &AppHandle) {
    let _ = app.emit_to(PANEL, "panel://toggle", ());
}

/// Size the panel and put it above the avatar, right edges aligned, kept
/// inside the avatar's screen. Sizes are logical (CSS) pixels.
pub fn place_panel(app: &AppHandle, width: f64, height: f64) -> tauri::Result<()> {
    let (Some(avatar), Some(panel)) = (
        app.get_webview_window(AVATAR),
        app.get_webview_window(PANEL),
    ) else {
        return Ok(());
    };
    let scale = panel.scale_factor()?;
    let size = PhysicalSize::new(
        (width * scale).round() as u32,
        (height * scale).round() as u32,
    );
    panel.set_size(size)?;
    let anchor = avatar.outer_position()?;
    let anchor_size = avatar.outer_size()?;
    let mut x = anchor.x + anchor_size.width as i32 - size.width as i32;
    let mut y = anchor.y - size.height as i32;
    if let Some(monitor) = avatar.current_monitor()? {
        let area = monitor.work_area();
        let (left, top) = (area.position.x, area.position.y);
        let right = left + area.size.width as i32 - size.width as i32;
        let bottom = top + area.size.height as i32 - size.height as i32;
        x = x.clamp(left, right.max(left));
        y = y.clamp(top, bottom.max(top));
    }
    panel.set_position(PhysicalPosition::new(x, y))
}

/// Show the panel. With `focus`, it takes the keyboard (you opened it to
/// type); without, it appears without taking it from the app you are typing
/// in (DESIGN.md section 1: no floating surface steals the focus).
pub fn show_panel(app: &AppHandle, focus: bool) -> tauri::Result<()> {
    match app.get_webview_window(PANEL) {
        Some(panel) => set_visible(&panel, true, focus),
        None => Ok(()),
    }
}

/// Show or hide one of our windows: the one way to do it, for all of them.
///
/// Straight through Win32, never through tao's show/hide: tao keeps its own
/// "visible" flag and only acts on a change of that flag, so a window shown
/// without activation (which tao cannot do) stayed on screen when asked to
/// hide, because tao believed it hidden already (found by checking the real
/// app: an empty panel left above the avatar after its toast).
pub fn set_visible(window: &WebviewWindow, visible: bool, focus: bool) -> tauri::Result<()> {
    #[cfg(windows)]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{
            ShowWindow, SW_HIDE, SW_SHOW, SW_SHOWNOACTIVATE,
        };
        let hwnd = window.hwnd()?.0 as _;
        let command = match (visible, focus) {
            (false, _) => SW_HIDE,
            (true, true) => SW_SHOW,
            (true, false) => SW_SHOWNOACTIVATE,
        };
        unsafe { ShowWindow(hwnd, command) };
        if visible && focus {
            window.set_focus()?;
        }
        Ok(())
    }
    #[cfg(not(windows))]
    {
        if visible {
            window.show()?;
        } else {
            window.hide()?;
        }
        if visible && focus {
            window.set_focus()?;
        }
        Ok(())
    }
}

/// Open the app window on `view`, or bring it forward and switch to it.
///
/// An ordinary window, framed and resizable, unlike the floating ones: it is
/// where you go to read or change things, so it takes the focus.
pub fn open_app_window(app: &AppHandle, view: &str) -> tauri::Result<()> {
    // "hooks/install": a known view, then an optional lowercase word for it.
    let (base, param) = view.split_once('/').unwrap_or((view, ""));
    if !APP_VIEWS.contains(&base) || !param.chars().all(|c| c.is_ascii_lowercase()) {
        return Ok(());
    }
    if let Some(window) = app.get_webview_window(APP) {
        let _ = app.emit_to(APP, "app://view", view);
        if window.is_minimized().unwrap_or(false) {
            window.unminimize()?;
        }
        return set_visible(&window, true, true);
    }
    let window =
        WebviewWindowBuilder::new(app, APP, WebviewUrl::App(format!("app.html#{view}").into()))
            .title("Little Wizard")
            .inner_size(860.0, 620.0)
            .min_inner_size(560.0, 420.0)
            .resizable(true)
            .visible(false)
            .build()?;
    protect::apply(&window);
    // Closed means hidden: it reopens at once, on the view asked for.
    let hide = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = set_visible(&hide, false, false);
        }
    });
    set_visible(&window, true, true)
}

/// Make the overlays match the monitors: one each, covering it exactly.
///
/// Tauri has no "monitors changed" event, so this runs at startup and again
/// whenever the guide is about to draw (the overlay windows ask for it).
pub fn sync_overlays(app: &AppHandle) -> tauri::Result<()> {
    let monitors = app.available_monitors()?;
    let mut wanted = Vec::new();
    for (index, monitor) in monitors.iter().enumerate() {
        let screen_id = monitor
            .name()
            .cloned()
            .unwrap_or_else(|| format!("screen-{index}"));
        let label = overlay_label(&screen_id);
        let window = match app.get_webview_window(&label) {
            Some(window) => window,
            None => {
                let url = format!("overlay.html?screen={}", encode_query(&screen_id));
                let window = floating(app, &label, &url)
                    .focused(false)
                    .focusable(false)
                    .build()?;
                // Before click-through: that makes the window layered, and
                // Windows refuses the affinity on layered windows.
                protect::apply(&window);
                // Clicks go through to whatever is underneath, always.
                window.set_ignore_cursor_events(true)?;
                window
            }
        };
        // Physical pixels, so a screen at another scale factor is still
        // covered exactly.
        window.set_position(*monitor.position())?;
        window.set_size(PhysicalSize::new(
            monitor.size().width,
            monitor.size().height,
        ))?;
        wanted.push(label);
    }
    for (label, window) in app.webview_windows() {
        if label.starts_with(OVERLAY_PREFIX) && !wanted.contains(&label) {
            window.destroy()?;
        }
    }
    Ok(())
}

/// Window labels allow letters, digits, `-`, `/`, `:` and `_` only; a
/// Windows screen name is `\\.\DISPLAY1`.
fn overlay_label(screen_id: &str) -> String {
    let safe: String = screen_id
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect();
    format!("{OVERLAY_PREFIX}{safe}")
}

fn encode_query(value: &str) -> String {
    value
        .bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

#[tauri::command]
pub fn toggle_panel(app: AppHandle) {
    toggle(&app);
}

#[tauri::command]
pub fn panel_place(app: AppHandle, width: f64, height: f64) -> Result<(), String> {
    place_panel(&app, width, height).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn panel_show(app: AppHandle, focus: bool) -> Result<(), String> {
    show_panel(&app, focus).map_err(|e| e.to_string())
}

/// Where the guide cursor is born: the orb at the tip of the avatar's staff,
/// physical pixels of the desktop (DESIGN.md section 6).
#[tauri::command]
pub fn avatar_anchor(app: AppHandle) -> Option<crate::cursor::Cursor> {
    let avatar = app.get_webview_window(AVATAR)?;
    let at = avatar.outer_position().ok()?;
    let scale = avatar.scale_factor().ok()?;
    // The orb, in the window's CSS pixels: 8 of padding, then (49, 15) on
    // the 56-wide figure (avatar/draw.ts).
    let scale = scale * avatar_scale();
    Some(crate::cursor::Cursor {
        x: at.x + (57.0 * scale).round() as i32,
        y: at.y + (23.0 * scale).round() as i32,
    })
}

/// The avatar's size and whether clicks go through him (config.toml,
/// `[appearance]`), told by his page. Grows and shrinks from his bottom-right
/// corner, so he stays where he sits on the taskbar.
#[tauri::command]
pub fn avatar_appearance(app: AppHandle, scale: f64, click_through: bool) -> Result<(), String> {
    let Some(avatar) = app.get_webview_window(AVATAR) else {
        return Ok(());
    };
    let scale = scale.clamp(0.5, 4.0);
    let run = || -> tauri::Result<()> {
        let before = avatar.outer_size()?;
        let at = avatar.outer_position()?;
        AVATAR_SCALE.store(scale.to_bits(), Ordering::SeqCst);
        let side = AVATAR_SIZE * scale;
        avatar.set_min_size(Some(LogicalSize::new(side, side)))?;
        avatar.set_size(LogicalSize::new(side, side))?;
        let after = avatar.outer_size()?;
        let moved = PhysicalPosition::new(
            at.x + before.width as i32 - after.width as i32,
            at.y + before.height as i32 - after.height as i32,
        );
        if moved != at {
            position::placing(moved);
            avatar.set_position(moved)?;
        }
        avatar.set_ignore_cursor_events(click_through)
    };
    run().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn app_window(app: AppHandle, view: String) -> Result<(), String> {
    open_app_window(&app, &view).map_err(|e| e.to_string())
}

/// For the pages: show or hide the window that asks (WindowEnv, the cloak).
#[tauri::command]
pub fn window_visible(window: WebviewWindow, visible: bool, focus: bool) -> Result<(), String> {
    set_visible(&window, visible, focus).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn overlays_sync(app: AppHandle) -> Result<(), String> {
    sync_overlays(&app).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screen_names_become_valid_labels() {
        assert_eq!(overlay_label(r"\\.\DISPLAY1"), "overlay-____DISPLAY1");
    }

    #[test]
    fn screen_names_are_encoded_for_the_url() {
        assert_eq!(encode_query(r"\\.\DISPLAY1"), "%5C%5C.%5CDISPLAY1");
    }
}
