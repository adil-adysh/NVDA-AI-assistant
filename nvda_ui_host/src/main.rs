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

    if let Err(e) = real_main() {
        eprintln!("ERROR: {:?}", e);
    }

    println!("Exiting...");
}

fn real_main() -> Result<()> {
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok()?;
        println!("COM initialized");

        let hwnd = window::create_window()?;
        println!("Window created: {:?}", hwnd);

        let prev_focus = window::focus_window(hwnd);
        println!("Window focused, previous focus HWND = {:?}", prev_focus);

        webview::init_webview(hwnd)?;
        window::run_message_loop();

        CoUninitialize();
    }

    Ok(())
}
