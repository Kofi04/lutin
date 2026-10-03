//! The windows of DESIGN.md section 2: avatar, panel, and one overlay per screen.
//!
//! Every window is created here, in Rust, rather than in tauri.conf.json:
//! their position depends on the monitors, and the overlays come and go with
//! them.

use tauri::{
    AppHandle, LogicalSize, Manager, PhysicalPosition, PhysicalSize, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

use crate::protect;

pub const AVATAR: &str = "avatar";
pub const PANEL: &str = "panel";
const OVERLAY_PREFIX: &str = "overlay-";

/// DESIGN.md section 4: a 56 px figure in a 72 px window.
const AVATAR_SIZE: f64 = 72.0;
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
    protect::apply(&avatar);
    avatar.show()?;

    let panel = floating(app, PANEL, "panel.html")
        .inner_size(PANEL_WIDTH, PANEL_HEIGHT)
        .focused(false)
        .build()?;
    protect::apply(&panel);

    sync_overlays(app)?;
    Ok(())
}

/// Bottom-right corner of the primary screen, just above the taskbar.
///
/// The work area is the screen minus the taskbar, wherever the taskbar is.
/// Remembering where the user dragged him is phase M4.
fn place_avatar(avatar: &WebviewWindow) -> tauri::Result<()> {
    let Some(monitor) = avatar.primary_monitor()? else {
        return Ok(());
    };
    let area = monitor.work_area();
    let scale = monitor.scale_factor();
    let size = ((AVATAR_SIZE + MARGIN) * scale).round() as i32;
    let x = area.position.x + area.size.width as i32 - size;
    let y = area.position.y + area.size.height as i32 - size;
    avatar.set_position(PhysicalPosition::new(x, y))
}

/// Show the panel above the avatar, kept inside the avatar's screen.
pub fn show_panel(app: &AppHandle) -> tauri::Result<()> {
    eprintln!("[windows] showing the panel");
    let (Some(avatar), Some(panel)) = (
        app.get_webview_window(AVATAR),
        app.get_webview_window(PANEL),
    ) else {
        return Ok(());
    };
    let anchor = avatar.outer_position()?;
    let anchor_size = avatar.outer_size()?;
    let size = panel.outer_size()?;
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
    panel.set_position(PhysicalPosition::new(x, y))?;
    panel.show()?;
    panel.set_focus()
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
pub fn toggle_panel(app: AppHandle) -> Result<(), String> {
    let Some(panel) = app.get_webview_window(PANEL) else {
        return Ok(());
    };
    if panel.is_visible().map_err(|e| e.to_string())? {
        panel.hide().map_err(|e| e.to_string())
    } else {
        show_panel(&app).map_err(|e| e.to_string())
    }
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
