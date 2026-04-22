use std::sync::OnceLock;
use windows::{
    core::{Result, w},
    Win32::{
        Foundation::*,
        UI::WindowsAndMessaging::GetClientRect,
    },
};

use webview2_com::Microsoft::Web::WebView2::Win32::*;
use webview2_com::{
    AddScriptToExecuteOnDocumentCreatedCompletedHandler,
    CreateCoreWebView2ControllerCompletedHandler,
    CreateCoreWebView2EnvironmentCompletedHandler,
    NavigationCompletedEventHandler,
    WebMessageReceivedEventHandler,
};

pub struct WebViewController(pub ICoreWebView2Controller);
unsafe impl Sync for WebViewController {}
unsafe impl Send for WebViewController {}

static WEBVIEW_CONTROLLER: OnceLock<WebViewController> = OnceLock::new();

pub fn resize_webview(hwnd: HWND) {
    if let Some(controller) = WEBVIEW_CONTROLLER.get() {
        let mut rect = RECT::default();
        let _ = unsafe { GetClientRect(hwnd, &mut rect) };
        unsafe {
            controller.0.SetBounds(rect).ok();
        }
    }
}

pub fn init_webview(hwnd: HWND) -> Result<()> {
    unsafe {
        println!("Initializing WebView2...");

        CreateCoreWebView2EnvironmentWithOptions(
            None,
            None,
            None,
            &CreateCoreWebView2EnvironmentCompletedHandler::create(Box::new(move |_hr: Result<()>, env: Option<ICoreWebView2Environment>| {
                println!("Environment created");

                let Some(env) = env else {
                    eprintln!("WebView2 environment callback returned None");
                    return Ok(());
                };

                env.CreateCoreWebView2Controller(
                    hwnd,
                    &CreateCoreWebView2ControllerCompletedHandler::create(Box::new(move |_hr: Result<()>, controller: Option<ICoreWebView2Controller>| {
                        println!("Controller created");

                        let Some(controller) = controller else {
                            eprintln!("WebView2 controller callback returned None");
                            return Ok(());
                        };

                        if WEBVIEW_CONTROLLER.set(WebViewController(controller.clone())).is_err() {
                            eprintln!("WEBVIEW_CONTROLLER already set");
                        }

                        let webview = match controller.CoreWebView2() {
                            Ok(webview) => webview,
                            Err(e) => {
                                eprintln!("CoreWebView2 retrieval failed: {:?}", e);
                                return Ok(());
                            }
                        };

                        controller.SetIsVisible(true).unwrap_or_else(|e| {
                            eprintln!("SetIsVisible failed: {:?}", e);
                        });

                        let mut rect = RECT::default();
                        let _ = GetClientRect(hwnd, &mut rect);
                        controller.SetBounds(rect).unwrap_or_else(|e| {
                            eprintln!("SetBounds failed: {:?}", e);
                        });

                        webview
                            .AddScriptToExecuteOnDocumentCreated(
                                w!(r#"
                                    window.chrome.webview.addEventListener('message', event => {
                                        const output = document.getElementById('host-message');
                                        if (output) {
                                            output.textContent = 'Host says: ' + event.data;
                                        }
                                    });

                                    window.sendMessageToHost = message => {
                                        window.chrome.webview.postMessage(message);
                                    };

                                    window.chrome.webview.postMessage('page loaded');
                                "#),
                                &AddScriptToExecuteOnDocumentCreatedCompletedHandler::create(
                                    Box::new(move |_hr: Result<()>, _script: String| {
                                        Ok(())
                                    }),
                                ),
                            )
                            .unwrap_or_else(|e| {
                                eprintln!("AddScriptToExecuteOnDocumentCreated failed: {:?}", e);
                            });

                        let mut token = 0i64;
                        if let Err(e) = webview.add_WebMessageReceived(
                            &WebMessageReceivedEventHandler::create(Box::new(
                                move |_sender: Option<ICoreWebView2>,
                                      args: Option<ICoreWebView2WebMessageReceivedEventArgs>| {
                                    let Some(args) = args else {
                                        eprintln!("WebMessageReceived args were None");
                                        return Ok(());
                                    };

                                    let mut message = windows::core::PWSTR::null();
                                    if let Err(e) = args.TryGetWebMessageAsString(&mut message) {
                                        eprintln!("TryGetWebMessageAsString failed: {:?}", e);
                                        return Ok(());
                                    }

                                    let message = message.to_string().unwrap_or_default();
                                    println!("JS -> host: {}", message);
                                    Ok(())
                                },
                            )),
                            &mut token,
                        ) {
                            eprintln!("add_WebMessageReceived failed: {:?}", e);
                        }

                        let controller_clone = controller.clone();
                        let mut nav_token = 0i64;
                        if let Err(e) = webview.add_NavigationCompleted(
                            &NavigationCompletedEventHandler::create(Box::new(move |_sender: Option<ICoreWebView2>, _args: Option<ICoreWebView2NavigationCompletedEventArgs>| {
                                println!("Navigation completed");
                                controller_clone.MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC).ok();
                                Ok(())
                            })),
                            &mut nav_token,
                        ) {
                            eprintln!("add_NavigationCompleted failed: {:?}", e);
                        }

                        if let Err(e) = webview.NavigateToString(
                            w!(r#"
                                <!DOCTYPE html>
                                <html lang="en">
                                <head>
                                    <meta charset="UTF-8">
                                    <title>NVDA UI Host</title>
                                </head>
                                <body>
                                    <h1>NVDA UI Host Local HTML</h1>
                                    <p id="host-message">Waiting for host message...</p>
                                    <button id="send-button">Send message to host</button>
                                    <script>
                                        document.getElementById('send-button').onclick = () => {
                                            window.sendMessageToHost('button clicked');
                                        };
                                    </script>
                                </body>
                                </html>
                            "#),
                        ) {
                            eprintln!("NavigateToString failed: {:?}", e);
                        }

                        if let Err(e) = webview.PostWebMessageAsString(w!("Hello from host")) {
                            eprintln!("PostWebMessageAsString failed: {:?}", e);
                        }

                        println!("Navigation started");

                        Ok(())
                    })),
                )
                .ok()
                .unwrap();

                Ok(())
            }))
        )
        .ok()
        .unwrap();
    }

    Ok(())
}
