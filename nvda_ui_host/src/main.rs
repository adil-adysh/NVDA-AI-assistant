mod app;
mod ipc;
mod protocol;
mod webview;
mod window;

use windows::{
    core::Result,
    Win32::System::Com::*,
};

fn main() {
    std::panic::set_hook(Box::new(|info| {
        eprintln!("PANIC: {:?}", info);
    }));

    println!("Starting NVDA UI Host...");
    println!("Application entrypoint reached");

    if let Err(e) = real_main() {
        eprintln!("ERROR: {:?}", e);
    } else {
        println!("real_main completed successfully");
    }

    println!("Exiting...");
}

fn real_main() -> Result<()> {
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok()?;
        println!("COM initialized");

        let hwnd = window::create_window()?;
        println!("Window created: {:?}", hwnd);

        window::initialize_host_dispatch(hwnd);
        let prev_focus = window::focus_window(hwnd);
        println!("Window focused, previous focus HWND = {:?}", prev_focus);

        webview::init_webview(hwnd)?;
        ipc::start_pipe_listener();
        println!("WebView initialization launched, entering message loop");
        window::run_message_loop();

        println!("Message loop exited, shutting down");
        CoUninitialize();
    }

    Ok(())
}
