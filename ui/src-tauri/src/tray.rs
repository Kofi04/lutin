//! The tray icon and its menu.
//!
//! Entries that are core actions are forwarded to the avatar window, whose
//! connection sends them to the core (`action { name }`): only the windows
//! speak the protocol, so there is one client implementation, not two.

use serde::Serialize;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager};

use crate::{position, supervisor, windows};

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

/// (menu id, label, app window view): the Qt menu's windows, now views.
const VIEWS: [(&str, &str, &str); 7] = [
    ("view-quick-note", "Note rapide", "notes/new"),
    ("view-clipboard", "Presse-papiers", "clipboard"),
    ("view-notes", "Notes", "notes"),
    ("view-reminders", "Me rappeler…", "reminders"),
    ("view-history", "Historique des discussions", "history"),
    ("view-agent", "Lancer un agent…", "agent"),
    ("view-settings", "Paramètres…", "settings"),
];

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let item = |id: &str, label: &str| MenuItem::with_id(app, id, label, true, None::<&str>);
    let menu = Menu::new(app)?;
    for (id, label, _) in ACTIONS {
        menu.append(&item(id, label)?)?;
    }
    menu.append(&PredefinedMenuItem::separator(app)?)?;
    for (id, label, _) in VIEWS {
        menu.append(&item(id, label)?)?;
    }
    menu.append(&PredefinedMenuItem::separator(app)?)?;
    menu.append(&item("toggle", "Masquer / Afficher le sorcier")?)?;
    menu.append(&item("snap", "Replacer sur la barre")?)?;
    menu.append(&item("restart", "Redémarrer le cœur")?)?;
    menu.append(&PredefinedMenuItem::separator(app)?)?;
    menu.append(&item("quit", "Quitter")?)?;

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
    if let Some((_, _, view)) = VIEWS.iter().find(|(menu_id, _, _)| *menu_id == id) {
        let _ = windows::open_app_window(app, view);
        return;
    }
    match id {
        "snap" => {
            position::forget(app);
            if let Some(avatar) = app.get_webview_window(windows::AVATAR) {
                let _ = windows::snap_avatar(&avatar);
            }
        }
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
