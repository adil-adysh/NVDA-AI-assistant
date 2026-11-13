use std::sync::Arc;

use axum::{
    Json, Router,
    extract::State,
    http::HeaderMap,
    routing::{get, post},
};
use mcp_client_prototype::{Command, Manager};
use rmcp::{
    ServerHandler,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{CallToolResult, ContentBlock, ServerCapabilities, ServerConfig},
    schemars, tool, tool_handler, tool_router,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService, session::local::LocalSessionManager,
    },
};
use serde::Deserialize;
use serde_json::Map;
use serde_json::json;
use std::collections::{BTreeMap, HashMap};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

#[derive(Debug, Deserialize, schemars::JsonSchema)]
struct EchoArgs {
    value: serde_json::Value,
}

#[derive(Clone)]
struct HttpFixture {
    tool_router: ToolRouter<Self>,
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

async fn connect_stdio(manager: &Manager, server_id: &str) {
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

async fn invoke(
    manager: &Manager,
    id: &str,
    server_id: &str,
    tool: &str,
) -> mcp_client_prototype::Reply {
    manager
        .handle(Command::Invoke {
            id: id.to_owned(),
            server_id: server_id.to_owned(),
            tool_name: tool.to_owned(),
            arguments: Map::from_iter([("value".to_owned(), json!({"n": 7}))]),
            timeout_ms: 5000,
            tool_call_id: Some(format!("tool-{id}")),
        })
        .await
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

    let a = invoke(&manager, "call-a", "stdio-a", "echo").await;
    let b = invoke(&manager, "call-b", "stdio-b", "echo").await;
    assert_eq!(a.body["structured_content"]["value"]["n"], 7);
    assert_eq!(a.body["server_id"], "stdio-a");
    assert_eq!(a.body["tool_call_id"], "tool-call-a");
    assert_eq!(a.body["uncertain"], false);
    assert_eq!(b.body["server_id"], "stdio-b");

    let failure = manager
        .handle(Command::Invoke {
            id: "tool-error".to_owned(),
            server_id: "stdio-a".to_owned(),
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
    let router = axum::Router::new().nest_service("/mcp", service);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server_stop = stop.clone();
    let server = tokio::spawn(async move {
        let _ = axum::serve(listener, router)
            .with_graceful_shutdown(server_stop.cancelled_owned())
            .await;
    });

    let manager = Manager::new();
    let connected = manager
        .handle(Command::ConnectHttp {
            id: "http-connect".to_owned(),
            server_id: "unrelated-http".to_owned(),
            url: format!("http://{address}/mcp"),
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

#[tokio::test]
async fn duplicate_request_ids_and_non_tls_remote_http_are_rejected() {
    let manager = Manager::new();
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
        })
        .await;
    assert_eq!(rejected.body["error"]["category"], "untrusted_endpoint");
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
    let called = manager
        .handle(Command::Invoke {
            id: "bridge-call".into(),
            server_id: "bridge".into(),
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
