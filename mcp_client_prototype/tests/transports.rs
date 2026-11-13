use std::sync::Arc;

use axum::{
    Json, Router,
    body::Body,
    extract::Request,
    extract::State,
    http::{HeaderMap, StatusCode, header::AUTHORIZATION},
    middleware::Next,
    response::{IntoResponse, Response},
    routing::{get, post},
};
use mcp_client_prototype::{Command, Manager, ManagerConfig};
use rmcp::{
    ErrorData, ServerHandler,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{
        CallToolResult, ContentBlock, ListToolsResult, PaginatedRequestParams, ServerCapabilities,
        ServerConfig, Tool,
    },
    schemars,
    service::{RequestContext, RoleServer},
    tool, tool_handler, tool_router,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
    },
};
use serde::Deserialize;
use serde_json::Map;
use serde_json::json;
use std::collections::{BTreeMap, HashMap};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::net::TcpListener;
use tokio::{
    io::{AsyncBufReadExt, AsyncWriteExt, BufReader},
    process::ChildStdin,
};
use tokio_util::sync::CancellationToken;

async fn send_manager_command(
    stdin: &mut ChildStdin,
    stdout: &mut BufReader<tokio::process::ChildStdout>,
    command: serde_json::Value,
) -> serde_json::Value {
    let mut frame = serde_json::to_vec(&command).unwrap();
    frame.push(b'\n');
    stdin.write_all(&frame).await.unwrap();
    stdin.flush().await.unwrap();
    loop {
        let mut line = String::new();
        assert_ne!(
            stdout.read_line(&mut line).await.unwrap(),
            0,
            "manager closed stdout before replying"
        );
        let response: serde_json::Value = serde_json::from_str(&line).unwrap();
        if response.get("id").is_some() {
            return response;
        }
    }
}

#[tokio::test]
async fn rejected_pre_handshake_invocations_do_not_consume_pending_capacity() {
    let mut manager = tokio::process::Command::new(env!("CARGO_BIN_EXE_mcp_manager"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = manager.stdin.take().unwrap();
    let mut stdout = BufReader::new(manager.stdout.take().unwrap());

    for index in 0..8 {
        let response = send_manager_command(
            &mut stdin,
            &mut stdout,
            json!({
                "op": "invoke", "id": format!("before-{index}"),
                "server_id": "not-connected", "manager_session_id": "stale",
                "server_incarnation": 1, "catalog_generation": 1,
                "tool_name": "echo", "arguments": {"value": 1}, "timeout_ms": 1000
            }),
        )
        .await;
        assert_eq!(response["error"]["category"], "handshake_required");
    }

    let hello = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"hello", "id":"hello-after-rejections", "protocol_version":1}),
    )
    .await;
    assert_eq!(hello["ok"], true);
    let connected = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({
            "op":"connect_stdio", "id":"connect-after-rejections", "server_id":"echo",
            "executable":env!("CARGO_BIN_EXE_mock_mcp"), "args":[], "env":{}
        }),
    )
    .await;
    assert_eq!(connected["ok"], true, "{connected:#}");
    let invoked = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({
            "op":"invoke", "id":"invoke-after-rejections", "server_id":"echo",
            "manager_session_id":connected["manager_session_id"],
            "server_incarnation":connected["server_incarnation"],
            "catalog_generation":connected["catalog_generation"],
            "tool_name":"echo", "arguments":{"value":1}, "timeout_ms":1000
        }),
    )
    .await;
    let _ = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"shutdown", "id":"shutdown-after-rejections"}),
    )
    .await;
    drop(stdin);
    tokio::time::timeout(Duration::from_secs(3), manager.wait())
        .await
        .expect("manager did not stop")
        .unwrap();
    assert_eq!(invoked["ok"], true, "{invoked:#}");
}

#[tokio::test]
async fn parent_eof_cancels_pending_initialization_and_exits_manager() {
    let marker = unique_marker("parent-eof");
    let mut manager = tokio::process::Command::new(env!("CARGO_BIN_EXE_mcp_manager"))
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = manager.stdin.take().unwrap();
    let mut hello =
        serde_json::to_vec(&json!({"op":"hello", "id":"eof-hello", "protocol_version":1})).unwrap();
    hello.push(b'\n');
    stdin.write_all(&hello).await.unwrap();
    stdin.flush().await.unwrap();

    let mut connect = serde_json::to_vec(&json!({
        "op":"connect_stdio", "id":"eof-connect", "server_id":"pending",
        "executable":env!("CARGO_BIN_EXE_mock_mcp"),
        "args":["--hang-init", marker.display().to_string()], "env":{}
    }))
    .unwrap();
    connect.push(b'\n');
    stdin.write_all(&connect).await.unwrap();
    stdin.flush().await.unwrap();
    wait_for_marker(&marker).await;
    let child_pid: u32 = tokio::fs::read_to_string(&marker)
        .await
        .unwrap()
        .parse()
        .unwrap();

    drop(stdin);
    tokio::time::timeout(Duration::from_secs(3), manager.wait())
        .await
        .expect("manager did not exit after parent EOF")
        .unwrap();
    #[cfg(windows)]
    wait_for_windows_process_exit(child_pid).await;
    let _ = tokio::fs::remove_file(marker).await;
}

#[tokio::test]
async fn manager_reply_does_not_discard_a_partial_next_command_frame() {
    let mut manager = tokio::process::Command::new(env!("CARGO_BIN_EXE_mcp_manager"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = manager.stdin.take().unwrap();
    let mut stdout = BufReader::new(manager.stdout.take().unwrap());
    let hello = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"hello", "id":"fragment-hello", "protocol_version":1}),
    )
    .await;
    assert_eq!(hello["ok"], true);

    let mut bytes = serde_json::to_vec(&json!({
        "op":"connect_stdio", "id":"fragment-connect", "server_id":"delayed",
        "executable":env!("CARGO_BIN_EXE_mock_mcp"), "args":["--delay-init"], "env":{}
    }))
    .unwrap();
    bytes.push(b'\n');
    bytes.extend_from_slice(b"{\"op\":\"status\",");
    stdin.write_all(&bytes).await.unwrap();
    stdin.flush().await.unwrap();

    let connected = tokio::time::timeout(Duration::from_secs(3), async {
        loop {
            let mut line = String::new();
            assert_ne!(stdout.read_line(&mut line).await.unwrap(), 0);
            let frame: serde_json::Value = serde_json::from_str(&line).unwrap();
            if frame.get("id") == Some(&json!("fragment-connect")) {
                break frame;
            }
        }
    })
    .await
    .expect("delayed connection did not complete");
    assert_eq!(connected["ok"], true, "{connected:#}");

    stdin
        .write_all(b"\"id\":\"status-fragmented\"}\n")
        .await
        .unwrap();
    stdin.flush().await.unwrap();
    let status = tokio::time::timeout(Duration::from_secs(1), async {
        loop {
            let mut line = String::new();
            if stdout.read_line(&mut line).await.unwrap() == 0 {
                return None;
            }
            let frame: serde_json::Value = serde_json::from_str(&line).unwrap();
            if frame.get("id") == Some(&json!("status-fragmented")) {
                return Some(frame);
            }
            if frame["error"]["category"] == "invalid_json" {
                return None;
            }
        }
    })
    .await
    .unwrap_or(None);

    let shutdown = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"shutdown", "id":"fragment-shutdown"}),
    )
    .await;
    drop(stdin);
    tokio::time::timeout(Duration::from_secs(3), manager.wait())
        .await
        .expect("manager did not stop")
        .unwrap();
    assert_eq!(shutdown["shutdown"], true);
    assert_eq!(status.expect("partial status frame was lost")["ok"], true);
}

#[tokio::test]
async fn oversized_completed_tool_result_preserves_uncertain_classification() {
    let mut manager = tokio::process::Command::new(env!("CARGO_BIN_EXE_mcp_manager"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut stdin = manager.stdin.take().unwrap();
    let mut stdout = BufReader::new(manager.stdout.take().unwrap());
    let _ = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"hello", "id":"large-hello", "protocol_version":1}),
    )
    .await;
    let connected = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({
            "op":"connect_stdio", "id":"large-connect", "server_id":"large",
            "executable":env!("CARGO_BIN_EXE_mock_mcp"), "args":[], "env":{}
        }),
    )
    .await;
    assert_eq!(connected["ok"], true, "{connected:#}");
    let result = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({
            "op":"invoke", "id":"large-invoke", "server_id":"large",
            "manager_session_id":connected["manager_session_id"],
            "server_incarnation":connected["server_incarnation"],
            "catalog_generation":connected["catalog_generation"],
            "tool_name":"large_result", "arguments":{}, "timeout_ms":5000,
            "tool_call_id":"call-large"
        }),
    )
    .await;
    let _ = send_manager_command(
        &mut stdin,
        &mut stdout,
        json!({"op":"shutdown", "id":"large-shutdown"}),
    )
    .await;
    drop(stdin);
    tokio::time::timeout(Duration::from_secs(3), manager.wait())
        .await
        .expect("manager did not stop")
        .unwrap();
    assert_eq!(result["ok"], false);
    assert_eq!(result["error"]["category"], "message_too_large");
    assert_eq!(result["uncertain"], true);
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
struct EchoArgs {
    value: serde_json::Value,
}

#[derive(Clone)]
struct HttpFixture {
    tool_router: ToolRouter<Self>,
}

async fn require_fixture_bearer(request: Request<Body>, next: Next) -> Response {
    let authorized = request
        .headers()
        .get(AUTHORIZATION)
        .and_then(|value| value.to_str().ok())
        == Some("Bearer fixture-secret");
    if authorized {
        next.run(request).await
    } else {
        StatusCode::UNAUTHORIZED.into_response()
    }
}

#[tool_router]
impl HttpFixture {
    fn new() -> Self {
        Self {
            tool_router: Self::tool_router(),
        }
    }

    #[tool(description = "Echo JSON over Streamable HTTP")]
    fn echo(&self, Parameters(EchoArgs { value }): Parameters<EchoArgs>) -> CallToolResult {
        let mut result = CallToolResult::success(vec![ContentBlock::text("http:echo")]);
        result.structured_content = Some(json!({"value": value, "transport": "http"}));
        result
    }

    #[tool(description = "Return a tool-level error")]
    fn tool_error(&self) -> CallToolResult {
        CallToolResult::error(vec![ContentBlock::text("fixture tool error")])
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for HttpFixture {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }
}

fn command_id(reply: &mcp_client_prototype::Reply) -> &str {
    &reply.id
}

async fn negotiate(manager: &Manager, id: &str) {
    let reply = manager
        .handle(Command::Hello {
            id: format!("hello-{id}"),
            protocol_version: 1,
        })
        .await;
    assert_eq!(reply.body["ok"], true, "{:#}", reply.body);
}

async fn connect_stdio(manager: &Manager, server_id: &str) {
    negotiate(manager, server_id).await;
    let reply = manager
        .handle(Command::ConnectStdio {
            id: format!("connect-{server_id}"),
            server_id: server_id.to_owned(),
            executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
            args: vec![],
            env: Default::default(),
        })
        .await;
    assert_eq!(command_id(&reply), format!("connect-{server_id}"));
    assert_eq!(reply.body["ok"], true, "{:#}", reply.body);
}

fn hang_init_command(server_id: &str, id: &str, marker: &Path) -> Command {
    Command::ConnectStdio {
        id: id.to_owned(),
        server_id: server_id.to_owned(),
        executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
        args: vec!["--hang-init".to_owned(), marker.display().to_string()],
        env: Default::default(),
    }
}

#[cfg(windows)]
fn spawn_grandchild_command(server_id: &str, id: &str, marker: &Path) -> Command {
    Command::ConnectStdio {
        id: id.to_owned(),
        server_id: server_id.to_owned(),
        executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
        args: vec![
            "--spawn-grandchild".to_owned(),
            marker.display().to_string(),
        ],
        env: Default::default(),
    }
}

fn unique_marker(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    std::env::temp_dir().join(format!("mcp-{name}-{}-{nonce}.marker", std::process::id()))
}

async fn wait_for_marker(marker: &Path) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while !marker.exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("fixture child did not start");
}

#[cfg(windows)]
async fn wait_for_windows_process_exit(pid: u32) {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, WAIT_OBJECT_0},
        System::Threading::{
            OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SYNCHRONIZE,
            WaitForSingleObject,
        },
    };
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let process = unsafe {
                OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE,
                    0,
                    pid,
                )
            };
            if process.is_null() {
                return;
            }
            let exited = unsafe { WaitForSingleObject(process, 0) == WAIT_OBJECT_0 };
            unsafe { CloseHandle(process) };
            if exited {
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("manager left the timed-out MCP child process running");
}

#[tokio::test]
async fn hanging_initialization_times_out_and_releases_server_reservation() {
    let marker = unique_marker("start");
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_millis(100),
        ..ManagerConfig::default()
    });
    negotiate(&manager, "startup-timeout").await;
    let first = manager
        .handle(hang_init_command("retryable", "hang-connect", &marker))
        .await;
    assert_eq!(first.body["error"]["category"], "startup_timeout");
    assert!(!manager.contains_server("retryable").await);
    #[cfg(windows)]
    wait_for_windows_process_exit(
        tokio::fs::read_to_string(&marker)
            .await
            .unwrap()
            .parse()
            .unwrap(),
    )
    .await;
    let retry = manager
        .handle(Command::ConnectStdio {
            id: "retry-connect".to_owned(),
            server_id: "retryable".to_owned(),
            executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
            args: vec![],
            env: Default::default(),
        })
        .await;
    assert_eq!(retry.body["ok"], true, "{:#}", retry.body);
    let _ = tokio::fs::remove_file(marker).await;
}

#[cfg(windows)]
#[tokio::test]
async fn cancelling_startup_kills_hostile_grandchild_in_manager_job_object() {
    let grandchild_marker = unique_marker("grandchild");
    let parent_marker = grandchild_marker.with_extension("parent");
    let manager = Manager::new();
    negotiate(&manager, "grandchild-cleanup").await;
    let child_marker_for_connect = grandchild_marker.clone();
    let connect = {
        let manager = manager.clone();
        tokio::spawn(async move {
            manager
                .handle(spawn_grandchild_command(
                    "hostile-tree",
                    "connect-hostile-tree",
                    &child_marker_for_connect,
                ))
                .await
        })
    };
    wait_for_marker(&grandchild_marker).await;
    wait_for_marker(&parent_marker).await;
    let grandchild_pid = tokio::fs::read_to_string(&grandchild_marker)
        .await
        .unwrap()
        .parse()
        .unwrap();
    let parent_pid = tokio::fs::read_to_string(&parent_marker)
        .await
        .unwrap()
        .parse()
        .unwrap();
    let disconnected = manager
        .handle(Command::Disconnect {
            id: "disconnect-hostile-tree".into(),
            server_id: "hostile-tree".into(),
        })
        .await;
    assert_eq!(disconnected.body["disconnected"], true);
    assert_eq!(
        connect.await.unwrap().body["error"]["category"],
        "cancelled"
    );
    wait_for_windows_process_exit(parent_pid).await;
    wait_for_windows_process_exit(grandchild_pid).await;
    let _ = tokio::fs::remove_file(grandchild_marker).await;
    let _ = tokio::fs::remove_file(parent_marker).await;
}

#[tokio::test]
async fn early_exit_and_malformed_server_fail_without_publishing_a_connection() {
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_millis(250),
        ..ManagerConfig::default()
    });
    negotiate(&manager, "startup-failure").await;
    for (id, mode) in [
        ("exit", "--exit-before-init"),
        ("malformed", "--malformed-init"),
    ] {
        let reply = manager
            .handle(Command::ConnectStdio {
                id: format!("connect-{id}"),
                server_id: id.to_owned(),
                executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
                args: vec![mode.to_owned()],
                env: Default::default(),
            })
            .await;
        assert!(
            ["protocol_error", "startup_timeout"]
                .contains(&reply.body["error"]["category"].as_str().unwrap_or_default()),
            "{:#}",
            reply.body
        );
        assert!(!manager.contains_server(id).await);
        let retry = manager
            .handle(Command::ConnectStdio {
                id: format!("retry-{id}"),
                server_id: id.to_owned(),
                executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
                args: vec![],
                env: Default::default(),
            })
            .await;
        assert_eq!(retry.body["ok"], true, "{:#}", retry.body);
    }
}

#[tokio::test]
async fn a_hanging_server_does_not_block_an_independent_connection() {
    let marker = unique_marker("independent");
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_secs(2),
        max_connections: 2,
        ..ManagerConfig::default()
    });
    negotiate(&manager, "isolated-startup").await;
    let first = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move {
            manager
                .handle(hang_init_command("slow", "slow-connect", &marker))
                .await
        }
    });
    wait_for_marker(&marker).await;
    let fast = tokio::time::timeout(
        Duration::from_millis(500),
        manager.handle(Command::ConnectStdio {
            id: "fast-connect".to_owned(),
            server_id: "fast".to_owned(),
            executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
            args: vec![],
            env: Default::default(),
        }),
    )
    .await
    .expect("hanging server blocked unrelated server startup");
    assert_eq!(fast.body["ok"], true, "{:#}", fast.body);
    manager
        .handle(Command::Disconnect {
            id: "disconnect-slow".into(),
            server_id: "slow".into(),
        })
        .await;
    assert_eq!(first.await.unwrap().body["error"]["category"], "cancelled");
    let _ = tokio::fs::remove_file(marker).await;
}

#[tokio::test]
async fn global_invocation_capacity_rejects_without_dispatch_and_returns_after_completion() {
    let manager = Manager::with_config(ManagerConfig {
        max_active_invocations: 1,
        max_invocations_per_server: 1,
        ..ManagerConfig::default()
    });
    connect_stdio(&manager, "global-a").await;
    connect_stdio(&manager, "global-b").await;
    let marker = unique_marker("global-invoke");
    let running = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move { invoke_slow(&manager, "slow-global", "global-a", &marker).await }
    });
    wait_for_exists(&marker).await;
    let rejected = invoke(&manager, "global-rejected", "global-b", "echo").await;
    assert_eq!(rejected.body["error"]["category"], "capacity");
    let completed = running.await.unwrap();
    assert_eq!(completed.body["ok"], true);
    let after = invoke(&manager, "global-after", "global-b", "echo").await;
    assert_eq!(after.body["ok"], true, "{:#}", after.body);
}

#[tokio::test]
async fn invocation_cancellation_returns_an_uncertain_result_without_retrying() {
    let manager = Manager::new();
    connect_stdio(&manager, "cancel-invocation").await;
    let marker = unique_marker("cancel-invocation");
    let started = Instant::now();
    let running = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move { invoke_slow(&manager, "cancel-target", "cancel-invocation", &marker).await }
    });
    wait_for_exists(&marker).await;
    let cancel = manager
        .handle(Command::Cancel {
            id: "cancel-control".into(),
            target_id: "cancel-target".into(),
        })
        .await;
    assert_eq!(cancel.body["cancellation_requested"], true);
    let result = tokio::time::timeout(Duration::from_millis(300), running)
        .await
        .expect("cancelled invocation kept waiting")
        .unwrap();
    assert_eq!(result.body["error"]["category"], "cancelled");
    assert_eq!(result.body["uncertain"], true);
    assert!(started.elapsed() < Duration::from_millis(500));
    let _ = tokio::fs::remove_file(marker).await;
}

#[tokio::test]
async fn per_server_saturation_does_not_block_other_servers() {
    let manager = Manager::with_config(ManagerConfig {
        max_active_invocations: 2,
        max_invocations_per_server: 1,
        ..ManagerConfig::default()
    });
    connect_stdio(&manager, "per-server-a").await;
    connect_stdio(&manager, "per-server-b").await;
    let marker = unique_marker("server-invoke");
    let running = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move { invoke_slow(&manager, "slow-server", "per-server-a", &marker).await }
    });
    wait_for_exists(&marker).await;
    let rejected = invoke(&manager, "same-server-rejected", "per-server-a", "echo").await;
    assert_eq!(rejected.body["error"]["category"], "capacity");
    let independent = invoke(&manager, "other-server-call", "per-server-b", "echo").await;
    assert_eq!(independent.body["ok"], true, "{:#}", independent.body);
    assert_eq!(running.await.unwrap().body["ok"], true);
    let after = invoke(&manager, "same-server-after", "per-server-a", "echo").await;
    assert_eq!(after.body["ok"], true, "{:#}", after.body);
}

#[tokio::test]
async fn concurrent_connect_reserves_id_before_starting_a_second_child() {
    let marker = unique_marker("race");
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_secs(2),
        ..ManagerConfig::default()
    });
    negotiate(&manager, "duplicate-reservation").await;
    let first = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move {
            manager
                .handle(hang_init_command("same-id", "first-connect", &marker))
                .await
        }
    });
    wait_for_marker(&marker).await;
    let second = manager
        .handle(Command::ConnectStdio {
            id: "second-connect".to_owned(),
            server_id: "same-id".to_owned(),
            executable: env!("CARGO_BIN_EXE_mock_mcp").to_owned(),
            args: vec![],
            env: Default::default(),
        })
        .await;
    assert_eq!(second.body["error"]["category"], "duplicate_server");
    manager
        .handle(Command::Disconnect {
            id: "cancel-first".into(),
            server_id: "same-id".into(),
        })
        .await;
    let first = first.await.unwrap();
    assert_eq!(first.body["error"]["category"], "cancelled");
    let _ = tokio::fs::remove_file(marker).await;
}

#[tokio::test]
async fn shutdown_cancels_pending_initialization_with_a_bounded_result() {
    let marker = unique_marker("shutdown");
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_secs(2),
        ..ManagerConfig::default()
    });
    negotiate(&manager, "shutdown-startup").await;
    let connect = tokio::spawn({
        let manager = manager.clone();
        let marker = marker.clone();
        async move {
            manager
                .handle(hang_init_command("shutdown-id", "pending", &marker))
                .await
        }
    });
    wait_for_marker(&marker).await;
    let started = Instant::now();
    let shutdown = manager
        .handle(Command::Shutdown {
            id: "shutdown-manager".into(),
        })
        .await;
    let failed_connect = connect.await.unwrap();
    assert_eq!(shutdown.body["shutdown"], true);
    assert_eq!(failed_connect.body["error"]["category"], "cancelled");
    assert!(started.elapsed() < Duration::from_millis(500));
    let _ = tokio::fs::remove_file(marker).await;
}

async fn invoke(
    manager: &Manager,
    id: &str,
    server_id: &str,
    tool: &str,
) -> mcp_client_prototype::Reply {
    let (manager_session_id, server_incarnation, catalog_generation) =
        identity(manager, server_id).await;
    manager
        .handle(Command::Invoke {
            id: id.to_owned(),
            server_id: server_id.to_owned(),
            manager_session_id,
            server_incarnation,
            catalog_generation,
            tool_name: tool.to_owned(),
            arguments: Map::from_iter([("value".to_owned(), json!({"n": 7}))]),
            timeout_ms: 5000,
            tool_call_id: Some(format!("tool-{id}")),
        })
        .await
}

async fn identity(manager: &Manager, server_id: &str) -> (String, u64, u64) {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let listed = manager
        .handle(Command::ListTools {
            id: format!("identity-{server_id}-{nonce}"),
            server_id: server_id.to_owned(),
        })
        .await;
    assert_eq!(listed.body["ok"], true, "{:#}", listed.body);
    (
        listed.body["manager_session_id"]
            .as_str()
            .unwrap()
            .to_owned(),
        listed.body["server_incarnation"].as_u64().unwrap(),
        listed.body["catalog_generation"].as_u64().unwrap(),
    )
}

async fn invoke_slow(
    manager: &Manager,
    id: &str,
    server_id: &str,
    marker: &Path,
) -> mcp_client_prototype::Reply {
    let (manager_session_id, server_incarnation, catalog_generation) =
        identity(manager, server_id).await;
    manager
        .handle(Command::Invoke {
            id: id.to_owned(),
            server_id: server_id.to_owned(),
            manager_session_id,
            server_incarnation,
            catalog_generation,
            tool_name: "slow".to_owned(),
            arguments: Map::from_iter([(
                "marker_path".to_owned(),
                json!(marker.display().to_string()),
            )]),
            timeout_ms: 5000,
            tool_call_id: Some(format!("tool-{id}")),
        })
        .await
}

async fn wait_for_exists(path: &Path) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while !path.exists() {
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("slow fixture tool did not start");
}

#[tokio::test]
async fn stdio_client_supports_two_servers_duplicate_names_and_structured_results() {
    let manager = Manager::new();
    connect_stdio(&manager, "stdio-a").await;
    connect_stdio(&manager, "stdio-b").await;

    for server in ["stdio-a", "stdio-b"] {
        let tools = manager
            .handle(Command::ListTools {
                id: format!("list-{server}"),
                server_id: server.to_owned(),
            })
            .await;
        assert_eq!(tools.body["ok"], true, "{:#}", tools.body);
        assert!(
            tools.body["tools"]
                .as_array()
                .unwrap()
                .iter()
                .any(|tool| tool["name"] == "echo"),
            "{:#}",
            tools.body
        );
    }

    let (manager_session_id, current_incarnation, current_generation) =
        identity(&manager, "stdio-a").await;
    let stale = manager
        .handle(Command::Invoke {
            id: "stale-generation".into(),
            server_id: "stdio-a".into(),
            manager_session_id: manager_session_id.clone(),
            server_incarnation: current_incarnation,
            catalog_generation: current_generation.saturating_add(1),
            tool_name: "echo".into(),
            arguments: Map::new(),
            timeout_ms: 5000,
            tool_call_id: None,
        })
        .await;
    assert_eq!(stale.body["error"]["category"], "stale_catalog");
    let stale_connection = manager
        .handle(Command::Invoke {
            id: "stale-incarnation".into(),
            server_id: "stdio-a".into(),
            manager_session_id: manager_session_id.clone(),
            server_incarnation: current_incarnation.saturating_add(1),
            catalog_generation: current_generation,
            tool_name: "echo".into(),
            arguments: Map::new(),
            timeout_ms: 5000,
            tool_call_id: None,
        })
        .await;
    assert_eq!(stale_connection.body["error"]["category"], "stale_server");
    let stale_manager = manager
        .handle(Command::Invoke {
            id: "stale-manager".into(),
            server_id: "stdio-a".into(),
            manager_session_id: "previous-manager-process".into(),
            server_incarnation: current_incarnation,
            catalog_generation: current_generation,
            tool_name: "echo".into(),
            arguments: Map::new(),
            timeout_ms: 5000,
            tool_call_id: None,
        })
        .await;
    assert_eq!(stale_manager.body["error"]["category"], "stale_manager");

    let a = invoke(&manager, "call-a", "stdio-a", "echo").await;
    let b = invoke(&manager, "call-b", "stdio-b", "echo").await;
    assert_eq!(a.body["structured_content"]["value"]["n"], 7);
    assert_eq!(a.body["server_id"], "stdio-a");
    assert_eq!(a.body["tool_call_id"], "tool-call-a");
    assert_eq!(a.body["uncertain"], false);
    assert_eq!(b.body["server_id"], "stdio-b");

    let (manager_session_id, server_incarnation, catalog_generation) =
        identity(&manager, "stdio-a").await;
    let failure = manager
        .handle(Command::Invoke {
            id: "tool-error".to_owned(),
            server_id: "stdio-a".to_owned(),
            manager_session_id: manager_session_id.clone(),
            server_incarnation,
            catalog_generation,
            tool_name: "tool_error".to_owned(),
            arguments: Map::new(),
            timeout_ms: 5000,
            tool_call_id: None,
        })
        .await;
    assert_eq!(failure.body["ok"], true);
    assert_eq!(
        failure.body["is_error"], true,
        "tool errors stay distinct from JSON-RPC failures"
    );
    assert_eq!(failure.body["error_source"], "tool");

    let protocol_failure = manager
        .handle(Command::Invoke {
            id: "protocol-error".to_owned(),
            server_id: "stdio-a".to_owned(),
            manager_session_id,
            server_incarnation,
            catalog_generation,
            tool_name: "missing".to_owned(),
            arguments: Map::new(),
            timeout_ms: 5000,
            tool_call_id: None,
        })
        .await;
    assert_eq!(protocol_failure.body["ok"], false);
    assert_eq!(protocol_failure.body["error"]["category"], "protocol_error");
    assert_eq!(protocol_failure.body["uncertain"], true);

    manager
        .handle(Command::Shutdown {
            id: "shutdown".to_owned(),
        })
        .await;
}

#[tokio::test]
async fn streamable_http_client_negotiates_and_calls_unrelated_server() {
    let stop = CancellationToken::new();
    let service = StreamableHttpService::new(
        || Ok(HttpFixture::new()),
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default()
            .with_json_response(true)
            .with_cancellation_token(stop.child_token()),
    );
    let router = axum::Router::new()
        .nest_service("/mcp", service)
        .layer(axum::middleware::from_fn(require_fixture_bearer));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_stop = stop.clone();
    let server = tokio::spawn(async move {
        let _ = axum::serve(listener, router)
            .with_graceful_shutdown(server_stop.cancelled_owned())
            .await;
    });

    let manager = Manager::new();
    negotiate(&manager, "http-success").await;
    let connected = manager
        .handle(Command::ConnectHttp {
            id: "http-connect".to_owned(),
            server_id: "unrelated-http".to_owned(),
            url: format!("http://{address}/mcp"),
            auth_token: Some("fixture-secret".to_owned()),
        })
        .await;
    assert_eq!(connected.body["ok"], true, "{:#}", connected.body);
    let listing = manager
        .handle(Command::ListTools {
            id: "http-list".to_owned(),
            server_id: "unrelated-http".to_owned(),
        })
        .await;
    assert!(
        listing.body["tools"]
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "echo"),
        "{:#}",
        listing.body
    );
    let result = invoke(&manager, "http-call", "unrelated-http", "echo").await;
    assert_eq!(result.body["structured_content"]["transport"], "http");
    assert_eq!(result.body["structured_content"]["value"]["n"], 7);
    manager
        .handle(Command::Shutdown {
            id: "http-shutdown".to_owned(),
        })
        .await;
    stop.cancel();
    server.await.unwrap();
}

#[derive(Clone)]
struct PaginatedFixture(Arc<AtomicUsize>);

impl ServerHandler for PaginatedFixture {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }

    async fn list_tools(
        &self,
        request: Option<PaginatedRequestParams>,
        _context: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        let page = usize::from(request.and_then(|params| params.cursor).is_some());
        self.0.fetch_add(1, Ordering::SeqCst);
        let tool = Tool::new(
            if page == 0 { "first" } else { "second" },
            "fixture tool",
            Arc::new(Map::new()),
        );
        let mut result = ListToolsResult::with_all_items(vec![tool]);
        if page == 0 {
            result.next_cursor = Some("next-page".to_owned());
        }
        Ok(result)
    }
}

#[tokio::test]
async fn bounded_catalog_stops_after_crossing_tool_count_limit() {
    let page_calls = Arc::new(AtomicUsize::new(0));
    let fixture_calls = page_calls.clone();
    let stop = CancellationToken::new();
    let service_stop = stop.child_token();
    let service = StreamableHttpService::new(
        move || Ok(PaginatedFixture(fixture_calls.clone())),
        Arc::new(LocalSessionManager::default()),
        StreamableHttpServerConfig::default()
            .with_json_response(true)
            .with_cancellation_token(service_stop),
    );
    let router = Router::new().nest_service("/mcp", service);
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_stop = stop.clone();
    let server = tokio::spawn(async move {
        let _ = axum::serve(listener, router)
            .with_graceful_shutdown(server_stop.cancelled_owned())
            .await;
    });

    let manager = Manager::with_config(ManagerConfig {
        max_tools_per_server: 1,
        ..ManagerConfig::default()
    });
    negotiate(&manager, "bounded-catalog").await;
    let connected = manager
        .handle(Command::ConnectHttp {
            id: "bounded-connect".to_owned(),
            server_id: "bounded".to_owned(),
            url: format!("http://{address}/mcp"),
            auth_token: None,
        })
        .await;
    assert_eq!(connected.body["ok"], true, "{:#}", connected.body);

    let listing = manager
        .handle(Command::ListTools {
            id: "bounded-list".to_owned(),
            server_id: "bounded".to_owned(),
        })
        .await;
    assert_eq!(
        listing.body["error"]["category"], "catalog_too_large",
        "{:#}",
        listing.body
    );
    assert_eq!(page_calls.load(Ordering::SeqCst), 2);

    manager
        .handle(Command::Shutdown {
            id: "bounded-shutdown".to_owned(),
        })
        .await;
    stop.cancel();
    server.await.unwrap();
}

#[tokio::test]
async fn streamable_http_initialization_is_bounded_and_releases_server_id() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = Router::new()
        .fallback(|| async { std::future::pending::<axum::response::Response>().await });
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let manager = Manager::with_config(ManagerConfig {
        startup_timeout: Duration::from_millis(100),
        ..ManagerConfig::default()
    });
    negotiate(&manager, "http-timeout").await;
    let started = Instant::now();
    let reply = manager
        .handle(Command::ConnectHttp {
            id: "http-hang".into(),
            server_id: "http-hang".into(),
            url: format!("http://{address}/mcp"),
            auth_token: None,
        })
        .await;
    assert_eq!(reply.body["error"]["category"], "startup_timeout");
    assert!(started.elapsed() < Duration::from_millis(500));
    assert!(!manager.contains_server("http-hang").await);
    server.abort();
}

#[tokio::test]
async fn duplicate_request_ids_and_non_tls_remote_http_are_rejected() {
    let manager = Manager::new();
    let before_handshake = manager
        .handle(Command::Status {
            id: "before-hello".into(),
        })
        .await;
    assert_eq!(
        before_handshake.body["error"]["category"],
        "handshake_required"
    );
    let rejected_hello = manager
        .handle(Command::Hello {
            id: "bad-hello".into(),
            protocol_version: 99,
        })
        .await;
    assert_eq!(rejected_hello.body["error"]["category"], "version_mismatch");
    negotiate(&manager, "after-rejected-hello").await;
    let first = manager
        .handle(Command::Status {
            id: "same".to_owned(),
        })
        .await;
    assert_eq!(first.body["ok"], true);
    let duplicate = manager
        .handle(Command::Status {
            id: "same".to_owned(),
        })
        .await;
    assert_eq!(duplicate.body["error"]["category"], "duplicate_id");
    let rejected = manager
        .handle(Command::ConnectHttp {
            id: "http-insecure".to_owned(),
            server_id: "remote".to_owned(),
            url: "http://example.com/mcp".to_owned(),
            auth_token: None,
        })
        .await;
    assert_eq!(rejected.body["error"]["category"], "untrusted_endpoint");
}

#[tokio::test]
async fn request_id_cache_evicts_old_ids_without_disabling_a_long_lived_manager() {
    let manager = Manager::with_config(ManagerConfig {
        max_request_ids: 2,
        ..ManagerConfig::default()
    });
    for id in ["old-id", "middle-id", "new-id"] {
        let reply = manager
            .handle(Command::Hello {
                id: id.to_owned(),
                protocol_version: 1,
            })
            .await;
        assert_eq!(reply.body["ok"], true);
    }
    let reused = manager
        .handle(Command::Status {
            id: "old-id".into(),
        })
        .await;
    assert_eq!(reused.body["ok"], true);
    let recent_duplicate = manager
        .handle(Command::Status {
            id: "old-id".into(),
        })
        .await;
    assert_eq!(recent_duplicate.body["error"]["category"], "duplicate_id");
}

#[tokio::test]
#[ignore = "requires the sibling Bridge executable built from D:\\nvda-addons\\nvda-mcp"]
async fn sibling_bridge_stdio_interoperability() {
    let executable = std::env::var("NVDA_MCP_BRIDGE_EXE")
        .expect("set NVDA_MCP_BRIDGE_EXE to the built nvda-mcp-server executable");
    let token = "phase3-local-test-token-32-bytes-long";
    let state = Arc::new(HashMap::from([("token".to_string(), token.to_string())]));
    let app = Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/tools", get(bridge_tools))
        .route(
            "/events",
            get(|| async { Json(json!({"events": [], "cursor": 0})) }),
        )
        .route("/action", post(bridge_action))
        .with_state(state);
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });

    let manager = Manager::new();
    assert!(
        manager
            .handle(Command::Hello {
                id: "bridge-hello".into(),
                protocol_version: 1
            })
            .await
            .body["ok"]
            .as_bool()
            .unwrap()
    );
    let connected = manager
        .handle(Command::ConnectStdio {
            id: "bridge-connect".into(),
            server_id: "bridge".into(),
            executable,
            args: vec![],
            env: BTreeMap::from([
                ("NVDA_BRIDGE_URL".into(), format!("http://{address}")),
                ("NVDA_BRIDGE_TOKEN".into(), token.into()),
                ("NVDA_BRIDGE_CATALOG_REFRESH_SECS".into(), "0".into()),
                ("LOG_LEVEL".into(), "ERROR".into()),
            ]),
        })
        .await;
    assert_eq!(connected.body["ok"], true, "{connected:?}");
    let tools = manager
        .handle(Command::ListTools {
            id: "bridge-list".into(),
            server_id: "bridge".into(),
        })
        .await;
    assert!(
        tools.body["tools"]
            .as_array()
            .unwrap()
            .iter()
            .any(|tool| tool["name"] == "health_ping")
    );
    let (manager_session_id, server_incarnation, catalog_generation) =
        identity(&manager, "bridge").await;
    let called = manager
        .handle(Command::Invoke {
            id: "bridge-call".into(),
            server_id: "bridge".into(),
            manager_session_id,
            server_incarnation,
            catalog_generation,
            tool_name: "health_ping".into(),
            arguments: serde_json::Map::new(),
            timeout_ms: 5000,
            tool_call_id: Some("python-contract-call".into()),
        })
        .await;
    assert_eq!(called.body["tool_name"], "health_ping");
    assert_eq!(called.body["is_error"], false);
    manager
        .handle(Command::Disconnect {
            id: "bridge-disconnect".into(),
            server_id: "bridge".into(),
        })
        .await;
    server.abort();
}

async fn bridge_tools(
    headers: HeaderMap,
    State(state): State<Arc<HashMap<String, String>>>,
) -> Json<serde_json::Value> {
    assert_eq!(
        headers
            .get("X-NVDA-Bridge-Token")
            .and_then(|value| value.to_str().ok()),
        state.get("token").map(String::as_str)
    );
    Json(json!({
        "protocol": "nvda-bridge-protocol", "protocol_version": "1.0.0", "bridge_version": "1.0.0",
        "api_level": 4, "supported_api_levels": [2,3,4], "types": {}, "count": 1,
        "tools": [{"name":"health_ping", "description":"Local test ping", "inputSchema":{"type":"object"}, "version":"1.0.0", "category":"system", "readOnly":true}]
    }))
}

async fn bridge_action(
    headers: HeaderMap,
    State(state): State<Arc<HashMap<String, String>>>,
    Json(payload): Json<serde_json::Value>,
) -> Json<serde_json::Value> {
    assert_eq!(
        headers
            .get("X-NVDA-Bridge-Token")
            .and_then(|value| value.to_str().ok()),
        state.get("token").map(String::as_str)
    );
    Json(json!({"success":true,"action":payload["action"],"data":{"pong":true}}))
}
