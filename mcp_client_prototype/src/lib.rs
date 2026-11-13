//! Standalone MCP client feasibility code. This crate is intentionally not a
//! runtime dependency of the NVDA add-on.
use std::{
    collections::{BTreeMap, HashMap},
    future::Future,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Duration,
};

use rmcp::{
    ClientHandler,
    model::{CallToolRequestParams, CallToolResult, ClientConfig},
    service::{ClientServiceExt, MaybeSendFuture, NotificationContext, RoleClient, RunningService},
    transport::{
        StreamableHttpClientTransport, TokioChildProcess,
        streamable_http_client::StreamableHttpClientTransportConfig,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt};
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;

const MAX_LINE_BYTES: usize = 1024 * 1024;

type Client = RunningService<RoleClient, ManagerClientHandler>;

#[derive(Clone)]
pub struct Manager {
    servers: Arc<RwLock<HashMap<String, Arc<ClientRecord>>>>,
    pending: Arc<RwLock<HashMap<String, CancellationToken>>>,
    used_request_ids: Arc<RwLock<HashMap<String, ()>>>,
    stopping: Arc<AtomicBool>,
    events: tokio::sync::broadcast::Sender<Value>,
}

struct ClientRecord {
    client: Arc<Client>,
    stopped: CancellationToken,
    transport: &'static str,
    catalog_generation: Arc<AtomicU64>,
}

#[derive(Clone)]
struct ManagerClientHandler {
    config: ClientConfig,
    server_id: String,
    events: tokio::sync::broadcast::Sender<Value>,
    catalog_generation: Arc<AtomicU64>,
}

impl ClientHandler for ManagerClientHandler {
    fn get_info(&self) -> ClientConfig {
        self.config.clone()
    }

    fn on_tool_list_changed(
        &self,
        _context: NotificationContext<RoleClient>,
    ) -> impl Future<Output = ()> + MaybeSendFuture + '_ {
        let generation = self.catalog_generation.fetch_add(1, Ordering::SeqCst) + 1;
        let _ = self.events.send(serde_json::json!({
            "event": "tool_list_changed",
            "server_id": self.server_id,
            "catalog_generation": generation,
        }));
        std::future::ready(())
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Command {
    Hello {
        id: String,
        protocol_version: u32,
    },
    ConnectStdio {
        id: String,
        server_id: String,
        executable: String,
        args: Vec<String>,
        #[serde(default)]
        env: BTreeMap<String, String>,
    },
    ConnectHttp {
        id: String,
        server_id: String,
        url: String,
    },
    Disconnect {
        id: String,
        server_id: String,
    },
    Status {
        id: String,
    },
    ListTools {
        id: String,
        server_id: String,
    },
    Invoke {
        id: String,
        server_id: String,
        tool_name: String,
        arguments: Map<String, Value>,
        timeout_ms: u64,
        #[serde(default)]
        tool_call_id: Option<String>,
    },
    Cancel {
        id: String,
        target_id: String,
    },
    Shutdown {
        id: String,
    },
}

#[derive(Debug, Serialize)]
pub struct Reply {
    pub id: String,
    #[serde(flatten)]
    pub body: Value,
}

impl Manager {
    pub fn new() -> Self {
        let (events, _) = tokio::sync::broadcast::channel(64);
        Self {
            servers: Arc::new(RwLock::new(HashMap::new())),
            pending: Arc::new(RwLock::new(HashMap::new())),
            used_request_ids: Arc::new(RwLock::new(HashMap::new())),
            stopping: Arc::new(AtomicBool::new(false)),
            events,
        }
    }

    pub async fn handle(&self, command: Command) -> Reply {
        let id = command_id(&command).to_owned();
        if id.is_empty() || id.len() > 128 {
            return reply(
                id,
                serde_json::json!({"ok": false, "error": {"category": "invalid_request", "message": "request id must be 1..128 bytes"}}),
            );
        }
        if let Err(body) = self.claim_id(&id).await {
            return reply(id, body);
        }
        self.handle_claimed(command).await
    }

    async fn claim_id(&self, id: &str) -> Result<(), Value> {
        let mut used = self.used_request_ids.write().await;
        if used.len() >= 10_000 {
            return Err(error("capacity", "request id history is full"));
        }
        if used.insert(id.to_owned(), ()).is_some() {
            return Err(error("duplicate_id", "request id was already used"));
        }
        Ok(())
    }

    async fn handle_claimed(&self, command: Command) -> Reply {
        let id = command_id(&command).to_owned();
        match command {
            Command::Hello {
                protocol_version, ..
            } => reply(
                id,
                serde_json::json!({
                    "ok": protocol_version == 1,
                    "protocol_version": 1,
                    "manager": "mcp-client-prototype",
                    "error": if protocol_version == 1 { Value::Null } else { serde_json::json!({"category":"version_mismatch","supported":[1]}) }
                }),
            ),
            Command::ConnectStdio {
                server_id,
                executable,
                args,
                env,
                ..
            } => {
                self.connect_stdio(id, server_id, executable, args, env)
                    .await
            }
            Command::ConnectHttp { server_id, url, .. } => {
                self.connect_http(id, server_id, url).await
            }
            Command::Disconnect { server_id, .. } => {
                let record = self.servers.write().await.remove(&server_id);
                if let Some(record) = record {
                    record.stopped.cancel();
                    record.client.cancellation_token().cancel();
                    reply(id, serde_json::json!({"ok": true, "server_id": server_id}))
                } else {
                    reply(id, error("not_connected", "server is not connected"))
                }
            }
            Command::Status { .. } => {
                let servers = self.servers.read().await;
                let values: Vec<_> = servers.iter().map(|(server_id, record)| serde_json::json!({
                    "server_id": server_id,
                    "transport": record.transport,
                    "connected": !record.client.is_closed() && !record.stopped.is_cancelled(),
                    "catalog_generation": record.catalog_generation.load(Ordering::SeqCst)
                })).collect();
                reply(id, serde_json::json!({"ok": true, "servers": values}))
            }
            Command::ListTools { server_id, .. } => match self.get_client(&server_id).await {
                Ok(record) => match record.client.list_all_tools().await {
                    Ok(tools) => reply(
                        id,
                        serde_json::json!({"ok": true, "server_id": server_id, "catalog_generation": record.catalog_generation.load(Ordering::SeqCst), "tools": tools}),
                    ),
                    Err(_err) => reply(id, protocol_error(false)),
                },
                Err(body) => reply(id, body),
            },
            Command::Invoke {
                server_id,
                tool_name,
                arguments,
                timeout_ms,
                tool_call_id,
                ..
            } => {
                let record = match self.get_client(&server_id).await {
                    Ok(record) => record,
                    Err(body) => return reply(id, body),
                };
                let cancelled = {
                    let mut pending = self.pending.write().await;
                    pending
                        .entry(id.clone())
                        .or_insert_with(CancellationToken::new)
                        .clone()
                };
                let timeout = Duration::from_millis(timeout_ms.clamp(1, 300_000));
                let params =
                    CallToolRequestParams::new(tool_name.clone()).with_arguments(arguments);
                let result = tokio::select! {
                    _ = cancelled.cancelled() => reply(id.clone(), uncertain("cancelled", "invocation cancellation requested; remote side effects may have occurred")),
                    _ = record.stopped.cancelled() => reply(id.clone(), uncertain("disconnected", "server disconnected while invocation was in flight")),
                    result = tokio::time::timeout(timeout, record.client.call_tool(params)) => match result {
                        Ok(Ok(result)) => tool_result(id.clone(), server_id, tool_name, tool_call_id, record.catalog_generation.load(Ordering::SeqCst), result),
                        Ok(Err(_err)) => reply(id.clone(), protocol_error(true)),
                        Err(_) => reply(id.clone(), uncertain("timeout", "invocation timed out; remote side effects may have occurred")),
                    }
                };
                self.pending.write().await.remove(&id);
                result
            }
            Command::Cancel { target_id, .. } => {
                let token = self.pending.read().await.get(&target_id).cloned();
                match token {
                    Some(token) => {
                        token.cancel();
                        reply(
                            id,
                            serde_json::json!({"ok": true, "target_id": target_id, "cancellation_requested": true}),
                        )
                    }
                    None => reply(
                        id,
                        error("not_running", "no invocation is running with that id"),
                    ),
                }
            }
            Command::Shutdown { .. } => {
                self.stopping.store(true, Ordering::SeqCst);
                self.pending
                    .read()
                    .await
                    .values()
                    .for_each(CancellationToken::cancel);
                let servers = std::mem::take(&mut *self.servers.write().await);
                for record in servers.values() {
                    record.stopped.cancel();
                    record.client.cancellation_token().cancel();
                }
                reply(id, serde_json::json!({"ok": true, "shutdown": true}))
            }
        }
    }

    async fn connect_stdio(
        &self,
        id: String,
        server_id: String,
        executable: String,
        args: Vec<String>,
        env: BTreeMap<String, String>,
    ) -> Reply {
        if self.stopping.load(Ordering::SeqCst) {
            return reply(id, error("shutting_down", "manager is stopping"));
        }
        if server_id.is_empty() || server_id.len() > 128 || executable.is_empty() {
            return reply(
                id,
                error("invalid_request", "server id and executable are required"),
            );
        }
        if self.servers.read().await.contains_key(&server_id) {
            return reply(
                id,
                error("duplicate_server", "server id is already connected"),
            );
        }
        let mut command = tokio::process::Command::new(executable);
        command
            .args(args)
            .envs(env)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        #[cfg(windows)]
        let command = {
            let mut wrapped: process_wrap::tokio::CommandWrap = command.into();
            wrapped.wrap(process_wrap::tokio::JobObject);
            wrapped.wrap(process_wrap::tokio::KillOnDrop);
            wrapped
        };
        let (transport, stderr) = match TokioChildProcess::builder(command).spawn() {
            Ok(pair) => pair,
            Err(err) => return reply(id, error("launch_failed", &err.to_string())),
        };
        if let Some(mut stderr) = stderr {
            tokio::spawn(async move {
                tokio::io::copy(&mut stderr, &mut tokio::io::sink())
                    .await
                    .ok();
            });
        }
        let catalog_generation = Arc::new(AtomicU64::new(1));
        let handler = ManagerClientHandler {
            config: ClientConfig::default(),
            server_id: server_id.clone(),
            events: self.events.clone(),
            catalog_generation: catalog_generation.clone(),
        };
        let client = match handler
            .serve_with_lifecycle(transport, client_lifecycle())
            .await
        {
            Ok(client) => client,
            Err(_err) => return reply(id, protocol_error(false)),
        };
        let record = Arc::new(ClientRecord {
            client: Arc::new(client),
            stopped: CancellationToken::new(),
            transport: "stdio",
            catalog_generation,
        });
        self.start_tool_change_listener(&record, server_id.clone());
        if self.insert_server(server_id.clone(), record).await {
            reply(
                id,
                serde_json::json!({"ok": true, "server_id": server_id, "transport": "stdio"}),
            )
        } else {
            reply(
                id,
                error("duplicate_server", "server id is already connected"),
            )
        }
    }

    async fn connect_http(&self, id: String, server_id: String, url: String) -> Reply {
        if self.stopping.load(Ordering::SeqCst) {
            return reply(id, error("shutting_down", "manager is stopping"));
        }
        if server_id.is_empty() || server_id.len() > 128 {
            return reply(
                id,
                error("invalid_request", "server id must be 1..128 bytes"),
            );
        }
        if !trusted_http_endpoint(&url) {
            return reply(
                id,
                error(
                    "untrusted_endpoint",
                    "remote Streamable HTTP endpoints require HTTPS",
                ),
            );
        }
        if self.servers.read().await.contains_key(&server_id) {
            return reply(
                id,
                error("duplicate_server", "server id is already connected"),
            );
        }
        let transport = StreamableHttpClientTransport::from_config(
            StreamableHttpClientTransportConfig::with_uri(url),
        );
        let catalog_generation = Arc::new(AtomicU64::new(1));
        let handler = ManagerClientHandler {
            config: ClientConfig::default(),
            server_id: server_id.clone(),
            events: self.events.clone(),
            catalog_generation: catalog_generation.clone(),
        };
        let client = match handler
            .serve_with_lifecycle(transport, client_lifecycle())
            .await
        {
            Ok(client) => client,
            Err(_err) => return reply(id, protocol_error(false)),
        };
        let record = Arc::new(ClientRecord {
            client: Arc::new(client),
            stopped: CancellationToken::new(),
            transport: "streamable_http",
            catalog_generation,
        });
        self.start_tool_change_listener(&record, server_id.clone());
        if self.insert_server(server_id.clone(), record).await {
            reply(
                id,
                serde_json::json!({"ok": true, "server_id": server_id, "transport": "streamable_http"}),
            )
        } else {
            reply(
                id,
                error("duplicate_server", "server id is already connected"),
            )
        }
    }

    async fn insert_server(&self, id: String, record: Arc<ClientRecord>) -> bool {
        let mut servers = self.servers.write().await;
        if self.stopping.load(Ordering::SeqCst) || servers.contains_key(&id) {
            return false;
        }
        servers.insert(id, record);
        true
    }

    async fn get_client(&self, id: &str) -> Result<Arc<ClientRecord>, Value> {
        self.servers
            .read()
            .await
            .get(id)
            .cloned()
            .ok_or_else(|| error("not_connected", "server is not connected"))
    }

    fn start_tool_change_listener(&self, record: &Arc<ClientRecord>, server_id: String) {
        let protocol_version = record
            .client
            .peer_info()
            .map(|info| info.protocol_version.clone());
        if protocol_version != Some(rmcp::model::ProtocolVersion::V_2026_07_28) {
            return;
        }
        let client = record.client.clone();
        let stopped = record.stopped.clone();
        let generation = record.catalog_generation.clone();
        let events = self.events.clone();
        tokio::spawn(async move {
            let mut subscription = match client
                .listen(
                    rmcp::model::SubscriptionFilter::builder()
                        .tools_list_changed()
                        .build(),
                )
                .await
            {
                Ok(subscription) => subscription,
                Err(_error) => {
                    let _ = events.send(serde_json::json!({"event":"notification_stream_failed", "server_id":server_id, "action":"refresh_tool_catalog"}));
                    return;
                }
            };
            loop {
                tokio::select! {
                    _ = stopped.cancelled() => { let _ = subscription.cancel().await; break; },
                    notification = subscription.next() => match notification {
                        Ok(Some(rmcp::model::ServerNotification::ToolListChangedNotification(_))) => {
                            let catalog_generation = generation.fetch_add(1, Ordering::SeqCst) + 1;
                            let _ = events.send(serde_json::json!({"event":"tool_list_changed", "server_id":server_id, "catalog_generation":catalog_generation}));
                        }
                        Ok(Some(_)) => {},
                        Ok(None) | Err(_) => {
                            let _ = events.send(serde_json::json!({"event":"notification_stream_closed", "server_id":server_id, "action":"refresh_tool_catalog"}));
                            break;
                        }
                    }
                }
            }
        });
    }
}

impl Default for Manager {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn run_stdio() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    use tokio::{io::BufReader, task::JoinSet};
    let mut input = BufReader::new(tokio::io::stdin());
    let mut output = tokio::io::stdout();
    let manager = Manager::new();
    let mut event_rx = manager.events.subscribe();
    let (tx, mut rx) = tokio::sync::mpsc::channel::<Reply>(128);
    let mut tasks = JoinSet::new();
    let mut shutdown_id: Option<String> = None;
    loop {
        tokio::select! {
            line = read_bounded_line(&mut input, MAX_LINE_BYTES), if shutdown_id.is_none() => {
                match line? {
                    None => { manager.stopping.store(true, Ordering::SeqCst); manager.shutdown_connections().await; break; },
                    Some(Err(())) => { write_bounded(&mut output, &reply("".to_owned(), error("message_too_large", "command exceeds the one MiB frame limit"))).await?; },
                    Some(Ok(bytes)) => match serde_json::from_slice::<Command>(&bytes) {
                        Ok(command) => {
            let id = command_id(&command).to_owned();
                            let is_shutdown = matches!(command, Command::Shutdown { .. });
                            if let Err(body) = manager.claim_id(&id).await {
                                write_bounded(&mut output, &reply(id, body)).await?;
                                continue;
                            }
                            if let Command::Invoke { id, .. } = &command {
                                manager.pending.write().await.insert(id.clone(), CancellationToken::new());
                            }
                            if is_shutdown { shutdown_id = Some(id); }
                            let worker = manager.clone();
                            let tx = tx.clone();
                            tasks.spawn(async move { let _ = tx.send(worker.handle_claimed(command).await).await; });
                        }
                        Err(_) => write_bounded(&mut output, &reply("".to_owned(), error("invalid_json", "command is not valid manager protocol JSON"))).await?,
                    }
                }
            },
            Some(reply) = rx.recv() => {
                let reply_id = reply.id.clone();
                write_bounded(&mut output, &reply).await?;
                if shutdown_id.as_deref() == Some(&reply_id) {
                    manager.shutdown_connections().await;
                    let drain = async {
                        while !tasks.is_empty() {
                            let _ = tasks.join_next().await;
                        }
                    };
                    if tokio::time::timeout(Duration::from_secs(2), drain).await.is_err() {
                        tasks.abort_all();
                        while tasks.join_next().await.is_some() {}
                    }
                    break;
                }
            },
            event = event_rx.recv() => {
                match event {
                    Ok(event) => write_value_bounded(&mut output, &event).await?,
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(missed)) => write_value_bounded(&mut output, &serde_json::json!({"event":"resync_required","missed":missed})).await?,
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {},
                }
            },
            Some(_) = tasks.join_next(), if !tasks.is_empty() => {
                if let Some(id) = &shutdown_id {
                    // The shutdown reply is emitted through rx; continue draining until it arrives.
                    let _ = id;
                }
            },
            else => break,
        }
    }
    while let Some(task) = tasks.join_next().await {
        let _ = task;
    }
    Ok(())
}

async fn read_bounded_line<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
    max: usize,
) -> std::io::Result<Option<Result<Vec<u8>, ()>>> {
    let mut line = Vec::new();
    loop {
        let available = reader.fill_buf().await?;
        if available.is_empty() {
            return Ok((!line.is_empty()).then_some(Ok(line)));
        }
        if let Some(end) = available.iter().position(|byte| *byte == b'\n') {
            if line.len().saturating_add(end) > max {
                reader.consume(end + 1);
                return Ok(Some(Err(())));
            }
            line.extend_from_slice(&available[..end]);
            reader.consume(end + 1);
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            return Ok(Some(Ok(line)));
        }
        if line.len().saturating_add(available.len()) > max {
            let amount = available.len();
            reader.consume(amount);
            loop {
                let chunk = reader.fill_buf().await?;
                if chunk.is_empty() {
                    return Ok(Some(Err(())));
                }
                if let Some(end) = chunk.iter().position(|byte| *byte == b'\n') {
                    reader.consume(end + 1);
                    return Ok(Some(Err(())));
                }
                let amount = chunk.len();
                reader.consume(amount);
            }
        }
        line.extend_from_slice(available);
        let amount = available.len();
        reader.consume(amount);
    }
}

async fn write_bounded<W: tokio::io::AsyncWrite + Unpin>(
    writer: &mut W,
    reply: &Reply,
) -> std::io::Result<()> {
    let value = serde_json::to_value(reply).unwrap_or_else(|_| serde_json::json!({"id": reply.id, "ok": false, "error": {"category":"serialization_error"}}));
    write_value_bounded(writer, &value).await
}

async fn write_value_bounded<W: tokio::io::AsyncWrite + Unpin>(
    writer: &mut W,
    value: &Value,
) -> std::io::Result<()> {
    let bytes = serde_json::to_vec(value).unwrap_or_else(|_| {
        b"{\"ok\":false,\"error\":{\"category\":\"serialization_error\"}}".to_vec()
    });
    if bytes.len() > MAX_LINE_BYTES {
        let fallback = serde_json::json!({"id": value.get("id").and_then(Value::as_str), "ok": false, "error": {"category": "message_too_large", "message": "response exceeds the one MiB frame limit"}});
        writer
            .write_all(&serde_json::to_vec(&fallback).unwrap())
            .await?;
        writer.write_all(b"\n").await?;
    } else {
        writer.write_all(&bytes).await?;
        writer.write_all(b"\n").await?;
    }
    writer.flush().await
}

impl Manager {
    async fn shutdown_connections(&self) {
        self.pending
            .read()
            .await
            .values()
            .for_each(CancellationToken::cancel);
        let servers = std::mem::take(&mut *self.servers.write().await);
        for record in servers.values() {
            record.stopped.cancel();
            record.client.cancellation_token().cancel();
        }
    }
}

fn command_id(command: &Command) -> &str {
    match command {
        Command::Hello { id, .. }
        | Command::ConnectStdio { id, .. }
        | Command::ConnectHttp { id, .. }
        | Command::Disconnect { id, .. }
        | Command::Status { id }
        | Command::ListTools { id, .. }
        | Command::Invoke { id, .. }
        | Command::Cancel { id, .. }
        | Command::Shutdown { id } => id,
    }
}

fn reply(id: String, body: Value) -> Reply {
    Reply { id, body }
}
fn error(category: &str, message: &str) -> Value {
    serde_json::json!({"ok": false, "error": {"category": category, "message": message}})
}
fn protocol_error(uncertain: bool) -> Value {
    serde_json::json!({"ok": false, "uncertain": uncertain, "error": {"source": "mcp", "category": "protocol_error", "message": "MCP request failed at the protocol or transport boundary"}})
}
fn uncertain(category: &str, message: &str) -> Value {
    serde_json::json!({"ok": false, "uncertain": true, "error": {"category": category, "message": message}})
}
fn tool_result(
    id: String,
    server_id: String,
    tool_name: String,
    tool_call_id: Option<String>,
    catalog_generation: u64,
    result: CallToolResult,
) -> Reply {
    let is_error = result.is_error.unwrap_or(false);
    reply(
        id,
        serde_json::json!({"ok": true, "uncertain": false, "server_id": server_id, "tool_name": tool_name, "tool_call_id": tool_call_id, "catalog_generation": catalog_generation, "error_source": if is_error { Some("tool") } else { None }, "is_error": is_error, "content": result.content, "structured_content": result.structured_content, "meta": result.meta}),
    )
}

fn client_lifecycle() -> rmcp::service::ClientLifecycleMode {
    rmcp::service::ClientLifecycleMode::Auto {
        preferred_versions: vec![
            rmcp::model::ProtocolVersion::V_2026_07_28,
            rmcp::model::ProtocolVersion::V_2025_11_25,
        ],
        legacy_version: Some(rmcp::model::ProtocolVersion::V_2025_11_25),
    }
}

fn trusted_http_endpoint(input: &str) -> bool {
    let Ok(url) = url::Url::parse(input) else {
        return false;
    };
    if url.username() != "" || url.password().is_some() {
        return false;
    }
    match url.scheme() {
        "https" => true,
        "http" => match url.host() {
            Some(url::Host::Ipv4(address)) => address.is_loopback(),
            Some(url::Host::Ipv6(address)) => address.is_loopback(),
            Some(url::Host::Domain(domain)) => domain.eq_ignore_ascii_case("localhost"),
            None => false,
        },
        _ => false,
    }
}
