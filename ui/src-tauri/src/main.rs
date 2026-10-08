// No console window in release builds; in debug the console shows the logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cursor;
mod position;
mod protect;
mod supervisor;
mod tray;
mod windows;

use tauri::RunEvent;

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(supervisor::Supervisor::new())
        // Every menu's clicks, the tray's and the avatar's right-click one.
        .on_menu_event(|app, event| tray::on_menu(app, event.id().as_ref()))
        .invoke_handler(tauri::generate_handler![
            tray::avatar_menu,
            supervisor::core_endpoint,
            windows::toggle_panel,
            windows::panel_place,
            windows::panel_show,
            windows::window_visible,
            windows::app_window,
            windows::panel_release_focus,
            windows::overlay_interactive,
            windows::avatar_anchor,
            windows::avatar_appearance,
            protect::capture_exclusion,
            cursor::cursor_listen,
            cursor::cursor_now,
            windows::overlays_sync,
        ])
        .setup(|app| {
            let handle = app.handle();
            windows::create(handle)?;
            tray::create(handle)?;
            supervisor::start(handle.clone());
            cursor::start(handle.clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the Tauri application");

    app.run(|app, event| match event {
        // Closing a window must not quit: the tray is the way out.
        RunEvent::ExitRequested {
            code: None, api, ..
        } => api.prevent_exit(),
        RunEvent::Exit => supervisor::stop(app),
        _ => {}
    });
}
