//! Standalone MCP client feasibility code. This crate is intentionally not a
//! runtime dependency of the NVDA add-on.
use std::time::{SystemTime, UNIX_EPOCH};
use std::{
    collections::{BTreeMap, HashMap, HashSet, VecDeque},
    future::Future,
    io,
    process::Stdio,
    sync::{
        Arc,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::Duration,
};

use rmcp::{
    ClientHandler,
    model::{CallToolRequestParams, CallToolResult, ClientConfig, PaginatedRequestParams},
    service::{ClientServiceExt, MaybeSendFuture, NotificationContext, RoleClient, RunningService},
    transport::{
        StreamableHttpClientTransport, TokioChildProcess,
        streamable_http_client::StreamableHttpClientTransportConfig,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt};
use tokio::sync::{OwnedSemaphorePermit, RwLock, Semaphore};
use tokio_util::sync::CancellationToken;

const MAX_LINE_BYTES: usize = 1024 * 1024;
const MAX_CATALOG_PAGES: usize = 64;

type Client = RunningService<RoleClient, ManagerClientHandler>;

#[derive(Clone)]
pub struct Manager {
    servers: Arc<RwLock<HashMap<String, ServerEntry>>>,
    config: ManagerConfig,
    session_id: String,
    connection_slots: Arc<Semaphore>,
    command_slots: Arc<Semaphore>,
    control_slots: Arc<Semaphore>,
    invocation_slots: Arc<Semaphore>,
    handshaken: Arc<AtomicBool>,
    next_server_incarnation: Arc<AtomicU64>,
    pending: Arc<RwLock<HashMap<String, CancellationToken>>>,
    used_request_ids: Arc<RwLock<RequestIdHistory>>,
    stopping: Arc<AtomicBool>,
    events: tokio::sync::broadcast::Sender<Value>,
}

struct ClientRecord {
    client: Arc<Client>,
    stopped: CancellationToken,
    transport: &'static str,
    catalog_generation: Arc<AtomicU64>,
    server_incarnation: u64,
    invocation_slots: Arc<Semaphore>,
}

struct ServerEntry {
    incarnation: u64,
    state: ServerLifecycle,
    _permit: OwnedSemaphorePermit,
}

struct RequestIdHistory {
    used: HashSet<String>,
    order: VecDeque<String>,
    capacity: usize,
}

enum ServerLifecycle {
    Connecting(CancellationToken),
    Connected(Arc<ClientRecord>),
}

#[derive(Clone, Debug)]
pub struct ManagerConfig {
    pub startup_timeout: Duration,
    pub shutdown_timeout: Duration,
    pub request_timeout: Duration,
    pub max_connections: usize,
    pub max_active_commands: usize,
    pub max_control_commands: usize,
    pub max_active_invocations: usize,
    pub max_invocations_per_server: usize,
    pub max_tools_per_server: usize,
    pub max_catalog_bytes: usize,
    pub max_request_ids: usize,
}

impl Default for ManagerConfig {
    fn default() -> Self {
        Self {
            startup_timeout: Duration::from_secs(15),
            shutdown_timeout: Duration::from_secs(2),
            request_timeout: Duration::from_secs(30),
            max_connections: 8,
            max_active_commands: 32,
            max_control_commands: 8,
            max_active_invocations: 8,
            max_invocations_per_server: 4,
            max_tools_per_server: 512,
            max_catalog_bytes: 512 * 1024,
            max_request_ids: 10_000,
        }
    }
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
        #[serde(default)]
        auth_token: Option<String>,
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
        manager_session_id: String,
        server_incarnation: u64,
        catalog_generation: u64,
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
        Self::with_config(ManagerConfig::default())
    }

    pub fn with_config(mut config: ManagerConfig) -> Self {
        config.startup_timeout = config
            .startup_timeout
            .max(Duration::from_millis(1))
            .min(Duration::from_secs(60));
        config.shutdown_timeout = config
            .shutdown_timeout
            .max(Duration::from_millis(1))
            .min(Duration::from_secs(10));
        config.request_timeout = config
            .request_timeout
            .max(Duration::from_millis(1))
            .min(Duration::from_secs(300));
        config.max_connections = config.max_connections.clamp(1, 32);
        config.max_active_commands = config.max_active_commands.clamp(1, 128);
        config.max_control_commands = config.max_control_commands.clamp(1, 32);
        config.max_active_invocations = config.max_active_invocations.clamp(1, 32);
        config.max_invocations_per_server = config.max_invocations_per_server.clamp(1, 16);
        config.max_tools_per_server = config.max_tools_per_server.clamp(1, 4096);
        config.max_catalog_bytes = config.max_catalog_bytes.clamp(1024, MAX_LINE_BYTES);
        config.max_request_ids = config.max_request_ids.clamp(1, 100_000);
        let request_id_capacity = config.max_request_ids;
        let (events, _) = tokio::sync::broadcast::channel(64);
        Self {
            servers: Arc::new(RwLock::new(HashMap::new())),
            connection_slots: Arc::new(Semaphore::new(config.max_connections)),
            command_slots: Arc::new(Semaphore::new(config.max_active_commands)),
            control_slots: Arc::new(Semaphore::new(config.max_control_commands)),
            invocation_slots: Arc::new(Semaphore::new(config.max_active_invocations)),
            handshaken: Arc::new(AtomicBool::new(false)),
            next_server_incarnation: Arc::new(AtomicU64::new(1)),
            config,
            session_id: format!(
                "{:x}-{:x}",
                std::process::id(),
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_nanos()
            ),
            pending: Arc::new(RwLock::new(HashMap::new())),
            used_request_ids: Arc::new(RwLock::new(RequestIdHistory {
                used: HashSet::new(),
                order: VecDeque::new(),
                capacity: request_id_capacity,
            })),
            stopping: Arc::new(AtomicBool::new(false)),
            events,
        }
    }

    pub async fn contains_server(&self, server_id: &str) -> bool {
        self.servers.read().await.contains_key(server_id)
    }

    async fn reserve_server(
        &self,
        id: String,
        server_id: &str,
    ) -> Result<(u64, CancellationToken), Reply> {
        if self.stopping.load(Ordering::SeqCst) {
            return Err(reply(id, error("shutting_down", "manager is stopping")));
        }
        let permit = self
            .connection_slots
            .clone()
            .try_acquire_owned()
            .map_err(|_| reply(id.clone(), error("capacity", "connection limit reached")))?;
        let mut servers = self.servers.write().await;
        if servers.contains_key(server_id) {
            return Err(reply(
                id,
                error(
                    "duplicate_server",
                    "server id is already connecting or connected",
                ),
            ));
        }
        if self.stopping.load(Ordering::SeqCst) {
            return Err(reply(id, error("shutting_down", "manager is stopping")));
        }
        let incarnation = self.next_server_incarnation.fetch_add(1, Ordering::SeqCst);
        let cancellation = CancellationToken::new();
        servers.insert(
            server_id.to_owned(),
            ServerEntry {
                incarnation,
                state: ServerLifecycle::Connecting(cancellation.clone()),
                _permit: permit,
            },
        );
        Ok((incarnation, cancellation))
    }

    async fn finish_server_connect(
        &self,
        id: String,
        server_id: String,
        incarnation: u64,
        cancel: &CancellationToken,
        record: Arc<ClientRecord>,
    ) -> Reply {
        let installed = {
            let mut servers = self.servers.write().await;
            match servers.get_mut(&server_id) {
                Some(entry)
                    if entry.incarnation == incarnation
                        && matches!(entry.state, ServerLifecycle::Connecting(_))
                        && !cancel.is_cancelled()
                        && !self.stopping.load(Ordering::SeqCst) =>
                {
                    entry.state = ServerLifecycle::Connected(record.clone());
                    true
                }
                _ => false,
            }
        };
        if !installed {
            record.stopped.cancel();
            record.client.cancellation_token().cancel();
            self.remove_connecting(&server_id, incarnation).await;
            return reply(
                id,
                uncertain("cancelled", "connection startup was cancelled"),
            );
        }
        self.start_tool_change_listener(&record, server_id.clone());
        reply(
            id,
            serde_json::json!({
                "ok": true,
                "server_id": server_id,
                "manager_session_id": self.session_id,
                "transport": record.transport,
                "server_incarnation": record.server_incarnation,
                "catalog_generation": record.catalog_generation.load(Ordering::SeqCst),
                "protocol_version": record.client.peer_info().map(|info| info.protocol_version.to_string()),
            }),
        )
    }

    async fn remove_connecting(&self, server_id: &str, incarnation: u64) {
        let mut servers = self.servers.write().await;
        if servers.get(server_id).is_some_and(|entry| {
            entry.incarnation == incarnation
                && matches!(entry.state, ServerLifecycle::Connecting(_))
        }) {
            servers.remove(server_id);
        }
    }

    async fn fail_connect(
        &self,
        id: String,
        server_id: &str,
        incarnation: u64,
        category: &str,
        message: &str,
    ) -> Reply {
        self.remove_connecting(server_id, incarnation).await;
        reply(id, error(category, message))
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
        if id.is_empty() || id.len() > 128 {
            return Err(error("invalid_request", "request id must be 1..128 bytes"));
        }
        let mut used = self.used_request_ids.write().await;
        if used.used.contains(id) {
            return Err(error("duplicate_id", "request id was recently used"));
        }
        if used.order.len() >= used.capacity
            && let Some(expired) = used.order.pop_front()
        {
            used.used.remove(&expired);
        }
        let id = id.to_owned();
        used.order.push_back(id.clone());
        used.used.insert(id);
        Ok(())
    }

    async fn handle_claimed(&self, command: Command) -> Reply {
        let id = command_id(&command).to_owned();
        if !matches!(&command, Command::Hello { .. } | Command::Shutdown { .. })
            && !self.handshaken.load(Ordering::SeqCst)
        {
            return reply(
                id,
                error(
                    "handshake_required",
                    "negotiate the manager protocol before sending commands",
                ),
            );
        }
        match command {
            Command::Hello {
                protocol_version, ..
            } => {
                let accepted = protocol_version == 1;
                self.handshaken.store(accepted, Ordering::SeqCst);
                reply(
                    id,
                    serde_json::json!({
                        "ok": accepted,
                        "protocol_version": 1,
                        "manager": "mcp-client-prototype",
                        "error": if accepted { Value::Null } else { serde_json::json!({"category":"version_mismatch","supported":[1]}) }
                    }),
                )
            }
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
            Command::ConnectHttp {
                server_id,
                url,
                auth_token,
                ..
            } => self.connect_http(id, server_id, url, auth_token).await,
            Command::Disconnect { server_id, .. } => {
                let entry = self.servers.write().await.remove(&server_id);
                if let Some(entry) = entry {
                    match entry.state {
                        ServerLifecycle::Connecting(cancel) => cancel.cancel(),
                        ServerLifecycle::Connected(record) => {
                            record.stopped.cancel();
                            record.client.cancellation_token().cancel();
                        }
                    }
                }
                reply(
                    id,
                    serde_json::json!({"ok": true, "server_id": server_id, "disconnected": true}),
                )
            }
            Command::Status { .. } => {
                let servers = self.servers.read().await;
                let values: Vec<_> = servers
                    .iter()
                    .map(|(server_id, entry)| match &entry.state {
                        ServerLifecycle::Connecting(_) => serde_json::json!({
                            "server_id": server_id,
                            "manager_session_id": self.session_id,
                            "server_incarnation": entry.incarnation,
                            "state": "connecting",
                            "connected": false
                        }),
                        ServerLifecycle::Connected(record) => serde_json::json!({
                            "server_id": server_id,
                            "manager_session_id": self.session_id,
                            "server_incarnation": entry.incarnation,
                            "state": if record.client.is_closed() || record.stopped.is_cancelled() { "failed" } else { "connected" },
                            "transport": record.transport,
                            "connected": !record.client.is_closed() && !record.stopped.is_cancelled(),
                            "catalog_generation": record.catalog_generation.load(Ordering::SeqCst)
                        }),
                    })
                    .collect();
                reply(id, serde_json::json!({"ok": true, "servers": values}))
            }
            Command::ListTools { server_id, .. } => match self.get_client(&server_id).await {
                Ok(record) => {
                    // Bind the response to the generation whose list request began.
                    // Notifications may arrive while rmcp is fetching or serializing.
                    let requested_generation = record.catalog_generation.load(Ordering::SeqCst);
                    match tokio::time::timeout(
                        self.config.request_timeout,
                        list_tools_bounded(&record.client, &self.config),
                    )
                    .await
                    {
                        Ok(Ok(tools)) => {
                            if tools.len() > self.config.max_tools_per_server {
                                reply(
                                    id,
                                    error(
                                        "catalog_too_large",
                                        "server tool count exceeds the configured limit",
                                    ),
                                )
                            } else {
                                match serialize_limited(&tools, self.config.max_catalog_bytes)
                                    .and_then(|bytes| {
                                        serde_json::from_slice::<Value>(&bytes).map_err(|_| ())
                                    }) {
                                    Ok(tools) => {
                                        let current_generation =
                                            record.catalog_generation.load(Ordering::SeqCst);
                                        if current_generation != requested_generation {
                                            reply(
                                                id,
                                                error(
                                                    "stale_catalog",
                                                    "tool catalog changed during discovery; retry the list request",
                                                ),
                                            )
                                        } else {
                                            reply(
                                                id,
                                                serde_json::json!({"ok": true, "server_id": server_id, "manager_session_id": self.session_id, "server_incarnation": record.server_incarnation, "catalog_generation": requested_generation, "tools": tools}),
                                            )
                                        }
                                    }
                                    Err(()) => reply(
                                        id,
                                        error(
                                            "catalog_too_large",
                                            "serialized tool catalog exceeds the configured limit",
                                        ),
                                    ),
                                }
                            }
                        }
                        Ok(Err("catalog_too_large")) => reply(
                            id,
                            error(
                                "catalog_too_large",
                                "serialized tool catalog exceeds the configured limit",
                            ),
                        ),
                        Ok(Err("catalog_invalid_pagination")) => reply(
                            id,
                            error(
                                "catalog_invalid_pagination",
                                "tool catalog pagination exceeded its safety limits",
                            ),
                        ),
                        Ok(Err(_)) => reply(id, protocol_error(false)),
                        Err(_) => reply(
                            id,
                            error(
                                "request_timeout",
                                "tool catalog request exceeded its deadline",
                            ),
                        ),
                    }
                }
                Err(body) => reply(id, body),
            },
            Command::Invoke {
                server_id,
                manager_session_id,
                server_incarnation,
                catalog_generation,
                tool_name,
                arguments,
                timeout_ms,
                tool_call_id,
                ..
            } => {
                let result = async {
                    let record = match self.get_client(&server_id).await {
                        Ok(record) => record,
                        Err(body) => return reply(id.clone(), body),
                    };
                    if manager_session_id != self.session_id {
                        return reply(id.clone(), error("stale_manager", "MCP manager session changed"));
                    }
                    if server_incarnation != record.server_incarnation {
                        return reply(id.clone(), error("stale_server", "server connection incarnation changed"));
                    }
                    if catalog_generation != record.catalog_generation.load(Ordering::SeqCst) {
                        return reply(id.clone(), error("stale_catalog", "tool catalog generation changed"));
                    }
                    let _global_permit = match self.invocation_slots.clone().try_acquire_owned() {
                        Ok(permit) => permit,
                        Err(_) => return reply(id.clone(), error("capacity", "global invocation limit reached")),
                    };
                    let _server_permit = match record.invocation_slots.clone().try_acquire_owned() {
                        Ok(permit) => permit,
                        Err(_) => return reply(id.clone(), error("capacity", "per-server invocation limit reached")),
                    };
                    let cancelled = {
                        let mut pending = self.pending.write().await;
                        if pending.len() >= self.config.max_active_invocations
                            && !pending.contains_key(&id)
                        {
                            return reply(id.clone(), error("capacity", "pending cancellation limit reached"));
                        }
                        pending
                            .entry(id.clone())
                            .or_insert_with(CancellationToken::new)
                            .clone()
                    };
                    let timeout = Duration::from_millis(timeout_ms.clamp(1, 300_000));
                    let params =
                        CallToolRequestParams::new(tool_name.clone()).with_arguments(arguments);
                    tokio::select! {
                        _ = cancelled.cancelled() => reply(id.clone(), uncertain("cancelled", "invocation cancellation requested; remote side effects may have occurred")),
                        _ = record.stopped.cancelled() => reply(id.clone(), uncertain("disconnected", "server disconnected while invocation was in flight")),
                        result = tokio::time::timeout(timeout, record.client.call_tool(params)) => match result {
                            Ok(Ok(result)) => tool_result(id.clone(), server_id, self.session_id.clone(), tool_name, tool_call_id, record.catalog_generation.load(Ordering::SeqCst), result),
                            Ok(Err(_err)) => reply(id.clone(), protocol_error(true)),
                            Err(_) => reply(id.clone(), uncertain("timeout", "invocation timed out; remote side effects may have occurred")),
                        }
                    }
                }
                .await;
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
                for entry in servers.into_values() {
                    match entry.state {
                        ServerLifecycle::Connecting(cancel) => cancel.cancel(),
                        ServerLifecycle::Connected(record) => {
                            record.stopped.cancel();
                            record.client.cancellation_token().cancel();
                        }
                    }
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
        if server_id.is_empty() || server_id.len() > 128 || executable.is_empty() {
            return reply(
                id,
                error("invalid_request", "server id and executable are required"),
            );
        }
        let (incarnation, cancel) = match self.reserve_server(id.clone(), &server_id).await {
            Ok(reservation) => reservation,
            Err(reply) => return reply,
        };
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
            Err(_err) => {
                return self
                    .fail_connect(
                        id,
                        &server_id,
                        incarnation,
                        "launch_failed",
                        "server process could not be started",
                    )
                    .await;
            }
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
        let startup = handler.serve_with_lifecycle(transport, client_lifecycle());
        let client = tokio::select! {
            _ = cancel.cancelled() => {
                return self.fail_connect(id, &server_id, incarnation, "cancelled", "connection startup was cancelled").await;
            }
            result = tokio::time::timeout(self.config.startup_timeout, startup) => match result {
                Ok(Ok(client)) => client,
                Ok(Err(_err)) => {
                    return self.fail_connect(id, &server_id, incarnation, "protocol_error", "MCP initialization failed").await;
                }
                Err(_) => {
                    cancel.cancel();
                    return self.fail_connect(id, &server_id, incarnation, "startup_timeout", "MCP initialization exceeded its deadline").await;
                }
            }
        };
        let record = Arc::new(ClientRecord {
            client: Arc::new(client),
            stopped: CancellationToken::new(),
            transport: "stdio",
            catalog_generation,
            server_incarnation: incarnation,
            invocation_slots: Arc::new(Semaphore::new(self.config.max_invocations_per_server)),
        });
        self.finish_server_connect(id, server_id, incarnation, &cancel, record)
            .await
    }

    async fn connect_http(
        &self,
        id: String,
        server_id: String,
        url: String,
        auth_token: Option<String>,
    ) -> Reply {
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
        if auth_token.as_ref().is_some_and(|token| {
            token.len() > 8192 || !token.is_ascii() || token.contains('\r') || token.contains('\n')
        }) {
            return reply(id, error("invalid_request", "HTTP bearer token is invalid"));
        }
        let (incarnation, cancel) = match self.reserve_server(id.clone(), &server_id).await {
            Ok(reservation) => reservation,
            Err(reply) => return reply,
        };
        let mut http_config = StreamableHttpClientTransportConfig::with_uri(url);
        if let Some(token) = auth_token.filter(|token| !token.is_empty()) {
            http_config = http_config.auth_header(token);
        }
        let transport = StreamableHttpClientTransport::from_config(http_config);
        let catalog_generation = Arc::new(AtomicU64::new(1));
        let handler = ManagerClientHandler {
            config: ClientConfig::default(),
            server_id: server_id.clone(),
            events: self.events.clone(),
            catalog_generation: catalog_generation.clone(),
        };
        let startup = handler.serve_with_lifecycle(transport, client_lifecycle());
        let client = tokio::select! {
            _ = cancel.cancelled() => {
                return self.fail_connect(id, &server_id, incarnation, "cancelled", "connection startup was cancelled").await;
            }
            result = tokio::time::timeout(self.config.startup_timeout, startup) => match result {
                Ok(Ok(client)) => client,
                Ok(Err(_err)) => {
                    return self.fail_connect(id, &server_id, incarnation, "protocol_error", "MCP initialization failed").await;
                }
                Err(_) => {
                    cancel.cancel();
                    return self.fail_connect(id, &server_id, incarnation, "startup_timeout", "MCP initialization exceeded its deadline").await;
                }
            }
        };
        let record = Arc::new(ClientRecord {
            client: Arc::new(client),
            stopped: CancellationToken::new(),
            transport: "streamable_http",
            catalog_generation,
            server_incarnation: incarnation,
            invocation_slots: Arc::new(Semaphore::new(self.config.max_invocations_per_server)),
        });
        self.finish_server_connect(id, server_id, incarnation, &cancel, record)
            .await
    }

    async fn get_client(&self, id: &str) -> Result<Arc<ClientRecord>, Value> {
        let servers = self.servers.read().await;
        match servers.get(id).map(|entry| &entry.state) {
            Some(ServerLifecycle::Connected(record))
                if !record.client.is_closed() && !record.stopped.is_cancelled() =>
            {
                Ok(record.clone())
            }
            Some(ServerLifecycle::Connecting(_)) => Err(error(
                "connecting",
                "server initialization is still in progress",
            )),
            Some(ServerLifecycle::Connected(_)) => Err(error(
                "not_connected",
                "server connection is no longer active",
            )),
            None => Err(error("not_connected", "server is not connected")),
        }
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

async fn list_tools_bounded(
    client: &Client,
    config: &ManagerConfig,
) -> Result<Vec<rmcp::model::Tool>, &'static str> {
    let mut tools = Vec::new();
    let mut cursor = None;
    let mut seen_cursors = HashSet::new();
    for _ in 0..MAX_CATALOG_PAGES {
        let page = client
            .list_tools(Some(
                PaginatedRequestParams::default().with_cursor(cursor.clone()),
            ))
            .await
            .map_err(|_| "catalog_request_failed")?;
        if tools.len().saturating_add(page.tools.len()) > config.max_tools_per_server {
            return Err("catalog_too_large");
        }
        tools.extend(page.tools);
        if serialize_limited(&tools, config.max_catalog_bytes).is_err() {
            return Err("catalog_too_large");
        }
        cursor = page.next_cursor;
        let Some(next) = cursor.as_ref() else {
            return Ok(tools);
        };
        if !seen_cursors.insert(next.clone()) {
            return Err("catalog_invalid_pagination");
        }
    }
    Err("catalog_invalid_pagination")
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
    let mut input_frame = BoundedLineReader::default();
    loop {
        tokio::select! {
            line = read_bounded_line(&mut input, &mut input_frame, MAX_LINE_BYTES), if shutdown_id.is_none() => {
                match line? {
                    None => { manager.stopping.store(true, Ordering::SeqCst); manager.shutdown_connections().await; break; },
                    Some(Err(())) => { write_bounded(&mut output, &reply("".to_owned(), error("message_too_large", "command exceeds the one MiB frame limit"))).await?; },
                    Some(Ok(bytes)) => match serde_json::from_slice::<Command>(&bytes) {
                        Ok(command) => {
                            let id = command_id(&command).to_owned();
                            let is_shutdown = matches!(&command, Command::Shutdown { .. });
                            if let Err(body) = manager.claim_id(&id).await {
                                write_bounded(&mut output, &reply(id, body)).await?;
                                continue;
                            }
                            if let Command::Hello { protocol_version, .. } = &command {
                                manager.handshaken.store(*protocol_version == 1, Ordering::SeqCst);
                            }
                            let is_control = matches!(
                                &command,
                                Command::Hello { .. }
                                    | Command::Status { .. }
                                    | Command::Cancel { .. }
                                    | Command::Disconnect { .. }
                                    | Command::Shutdown { .. }
                            );
                            let permit = if is_control {
                                manager.control_slots.clone().try_acquire_owned()
                            } else {
                                manager.command_slots.clone().try_acquire_owned()
                            };
                            let permit = match permit {
                                Ok(permit) => permit,
                                Err(_) => {
                                    write_bounded(&mut output, &reply(id, error("capacity", "manager command limit reached"))).await?;
                                    continue;
                                }
                            };
                            if let Command::Invoke { id, .. } = &command {
                                let mut pending = manager.pending.write().await;
                                if pending.len() >= manager.config.max_active_invocations {
                                    write_bounded(&mut output, &reply(id.clone(), error("capacity", "pending invocation limit reached"))).await?;
                                    continue;
                                }
                                pending.insert(id.clone(), CancellationToken::new());
                            }
                            if is_shutdown { shutdown_id = Some(id); }
                            let worker = manager.clone();
                            let tx = tx.clone();
                            let is_invoke = matches!(&command, Command::Invoke { .. });
                            tasks.spawn(async move {
                                let _permit = permit;
                                let response = worker.handle_claimed(command).await;
                                if is_invoke {
                                    worker.pending.write().await.remove(&response.id);
                                }
                                let _ = tx.send(response).await;
                            });
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
    manager.shutdown_connections().await;
    let drain = async {
        while !tasks.is_empty() {
            let _ = tasks.join_next().await;
        }
    };
    if tokio::time::timeout(manager.config.shutdown_timeout, drain)
        .await
        .is_err()
    {
        tasks.abort_all();
        while tasks.join_next().await.is_some() {}
    }
    Ok(())
}

#[derive(Default)]
struct BoundedLineReader {
    line: Vec<u8>,
    discarding_oversized: bool,
}

async fn read_bounded_line<R: tokio::io::AsyncBufRead + Unpin>(
    reader: &mut R,
    state: &mut BoundedLineReader,
    max: usize,
) -> std::io::Result<Option<Result<Vec<u8>, ()>>> {
    loop {
        let available = reader.fill_buf().await?;
        if available.is_empty() {
            if state.discarding_oversized {
                state.discarding_oversized = false;
                state.line.clear();
                return Ok(Some(Err(())));
            }
            return Ok((!state.line.is_empty()).then(|| Ok(std::mem::take(&mut state.line))));
        }

        let newline = available.iter().position(|byte| *byte == b'\n');
        let content_len = newline.unwrap_or(available.len());
        if state.discarding_oversized {
            let consumed = newline.map_or(available.len(), |end| end + 1);
            reader.consume(consumed);
            if newline.is_some() {
                state.discarding_oversized = false;
                return Ok(Some(Err(())));
            }
            continue;
        }

        if state.line.len().saturating_add(content_len) > max {
            state.line.clear();
            if let Some(end) = newline {
                reader.consume(end + 1);
                return Ok(Some(Err(())));
            }
            let consumed = available.len();
            reader.consume(consumed);
            state.discarding_oversized = true;
            continue;
        }

        if let Some(end) = newline {
            state.line.extend_from_slice(&available[..end]);
            reader.consume(end + 1);
            if state.line.last() == Some(&b'\r') {
                state.line.pop();
            }
            return Ok(Some(Ok(std::mem::take(&mut state.line))));
        }

        state.line.extend_from_slice(available);
        let consumed = available.len();
        reader.consume(consumed);
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
    let fallback = serde_json::json!({
        "id": value.get("id").and_then(Value::as_str),
        "ok": false,
        "uncertain": value.get("uncertain").and_then(Value::as_bool).unwrap_or(false)
            || value.get("tool_name").is_some(),
        "error": {"category": "message_too_large", "message": "response exceeds the one MiB frame limit"}
    });
    let bytes = serialize_limited(value, MAX_LINE_BYTES)
        .unwrap_or_else(|_| serde_json::to_vec(&fallback).expect("bounded fallback serializes"));
    writer.write_all(&bytes).await?;
    writer.write_all(b"\n").await?;
    writer.flush().await
}

fn serialize_limited<T: Serialize>(value: &T, limit: usize) -> Result<Vec<u8>, ()> {
    struct LimitedBuffer {
        bytes: Vec<u8>,
        limit: usize,
    }
    impl io::Write for LimitedBuffer {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.bytes.len().saturating_add(bytes.len()) > self.limit {
                return Err(io::Error::other("serialized JSON exceeds its byte limit"));
            }
            self.bytes.extend_from_slice(bytes);
            Ok(bytes.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    let mut output = LimitedBuffer {
        bytes: Vec::with_capacity(limit.min(16 * 1024)),
        limit,
    };
    serde_json::to_writer(&mut output, value).map_err(|_| ())?;
    Ok(output.bytes)
}

impl Manager {
    async fn shutdown_connections(&self) {
        self.pending
            .read()
            .await
            .values()
            .for_each(CancellationToken::cancel);
        let servers = std::mem::take(&mut *self.servers.write().await);
        for entry in servers.into_values() {
            match entry.state {
                ServerLifecycle::Connecting(cancel) => cancel.cancel(),
                ServerLifecycle::Connected(record) => {
                    record.stopped.cancel();
                    record.client.cancellation_token().cancel();
                }
            }
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
    manager_session_id: String,
    tool_name: String,
    tool_call_id: Option<String>,
    catalog_generation: u64,
    result: CallToolResult,
) -> Reply {
    let is_error = result.is_error.unwrap_or(false);
    reply(
        id,
        serde_json::json!({"ok": true, "uncertain": false, "server_id": server_id, "manager_session_id": manager_session_id, "tool_name": tool_name, "tool_call_id": tool_call_id, "catalog_generation": catalog_generation, "error_source": if is_error { Some("tool") } else { None }, "is_error": is_error, "content": result.content, "structured_content": result.structured_content, "meta": result.meta}),
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
