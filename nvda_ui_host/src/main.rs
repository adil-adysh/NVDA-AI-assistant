mod app;
mod ipc;
mod logger;
mod protocol;
mod webview;
mod window;

use windows::{
    core::Result,
    Win32::System::Com::*,
};

fn main() {
    logger::init();

    std::panic::set_hook(Box::new(|info| {
        logger::error(&format!("PANIC: {:?}", info));
    }));

    logger::info("Starting NVDA UI Host...");
    logger::info("Application entrypoint reached");

    if let Err(e) = real_main() {
        logger::error(&format!("ERROR: {:?}", e));
    } else {
        logger::info("real_main completed successfully");
    }

    logger::info("Exiting...");
}

fn real_main() -> Result<()> {
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok()?;
        logger::info("COM initialized");

        let hwnd = window::create_window()?;
        logger::info(&format!("Window created: {:?}", hwnd));

        window::initialize_host_dispatch(hwnd);
        let prev_focus = window::focus_window(hwnd);
        logger::info(&format!("Window focused, previous focus HWND = {:?}", prev_focus));

        webview::init_webview(hwnd)?;
        ipc::start_pipe_listener();
        logger::info("WebView initialization launched, entering message loop");
        window::run_message_loop();

        logger::info("Message loop exited, shutting down");
        CoUninitialize();
    }

    Ok(())
}
