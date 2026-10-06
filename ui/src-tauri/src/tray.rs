//! The tray icon and its menu.
//!
//! Entries that are core actions are forwarded to the avatar window, whose
//! connection sends them to the core (`action { name }`): only the windows
//! speak the protocol, so there is one client implementation, not two.

use serde::Serialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};

use crate::{supervisor, windows};

#[derive(Clone, Serialize)]
struct TrayAction<'a> {
    name: &'a str,
}

/// (menu id, label, protocol action). Labels in French, like the Qt menu.
const ACTIONS: [(&str, &str, &str); 3] = [
    ("ask", "Demander à Claude…", "ask"),
    ("region", "Montrer une zone…", "capture.region"),
    ("screen", "Capturer l'écran", "capture.screen"),
];

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let mut items = Vec::new();
    for (id, label, _) in ACTIONS {
        items.push(MenuItem::with_id(app, id, label, true, None::<&str>)?);
    }
    let toggle = MenuItem::with_id(
        app,
        "toggle",
        "Masquer / Afficher le sorcier",
        true,
        None::<&str>,
    )?;
    let restart = MenuItem::with_id(app, "restart", "Redémarrer le cœur", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let separator2 = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &items[0],
            &items[1],
            &items[2],
            &separator,
            &toggle,
            &restart,
            &separator2,
            &quit,
        ],
    )?;

    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip("Little Wizard")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| on_menu(app, event.id().as_ref()))
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                windows::toggle(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

fn on_menu(app: &AppHandle, id: &str) {
    if let Some((_, _, action)) = ACTIONS.iter().find(|(menu_id, _, _)| *menu_id == id) {
        let _ = app.emit_to(
            windows::AVATAR,
            "tray://action",
            TrayAction { name: action },
        );
        return;
    }
    match id {
        "toggle" => {
            if let Some(avatar) = app.get_webview_window(windows::AVATAR) {
                let visible = avatar.is_visible().unwrap_or(true);
                let _ = windows::set_visible(&avatar, !visible, false);
            }
        }
        "restart" => supervisor::restart(app),
        "quit" => app.exit(0),
        _ => {}
    }
}
