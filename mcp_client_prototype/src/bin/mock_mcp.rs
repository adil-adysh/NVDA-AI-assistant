use rmcp::{
    ServerHandler,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::{CallToolResult, ContentBlock, ServerCapabilities, ServerConfig},
    schemars,
    service::ServiceExt,
    tool, tool_handler, tool_router,
};
use serde::Deserialize;

#[derive(Debug, Deserialize, schemars::JsonSchema)]
struct EchoArgs {
    value: serde_json::Value,
}

#[derive(Debug, Deserialize, schemars::JsonSchema)]
struct SlowArgs {
    marker_path: String,
}

#[derive(Clone)]
struct Fixture {
    prefix: &'static str,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl Fixture {
    fn new(prefix: &'static str) -> Self {
        Self {
            prefix,
            tool_router: Self::tool_router(),
        }
    }

    #[tool(description = "Echo one JSON value as structured content")]
    fn echo(&self, Parameters(EchoArgs { value }): Parameters<EchoArgs>) -> CallToolResult {
        let mut result =
            CallToolResult::success(vec![ContentBlock::text(format!("{}echo", self.prefix))]);
        result.structured_content =
            Some(serde_json::json!({"value": value, "prefix": self.prefix}));
        result
    }

    #[tool(description = "Return a tool-level error")]
    fn tool_error(&self) -> CallToolResult {
        CallToolResult::error(vec![ContentBlock::text("fixture tool error")])
    }

    #[tool(description = "Return an oversized result to test bounded manager replies")]
    fn large_result(&self) -> CallToolResult {
        CallToolResult::success(vec![ContentBlock::text("x".repeat(1_100_000))])
    }

    #[tool(description = "Write a marker and wait to exercise cancellation")]
    async fn slow(&self, Parameters(SlowArgs { marker_path }): Parameters<SlowArgs>) -> String {
        let _ = std::fs::write(marker_path, "running");
        tokio::time::sleep(std::time::Duration::from_millis(700)).await;
        "finished".to_owned()
    }
}

#[tool_handler(router = self.tool_router)]
impl ServerHandler for Fixture {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().is_some_and(|arg| arg == "--grandchild") {
        std::fs::write(&args[1], std::process::id().to_string())?;
        std::future::pending::<()>().await;
    }
    if args.first().is_some_and(|arg| arg == "--spawn-grandchild") {
        let marker = std::path::PathBuf::from(&args[1]);
        let _child = std::process::Command::new(std::env::current_exe()?)
            .args([
                "--grandchild",
                marker.to_str().ok_or("invalid marker path")?,
            ])
            .spawn()?;
        std::fs::write(
            marker.with_extension("parent"),
            std::process::id().to_string(),
        )?;
        std::future::pending::<()>().await;
    }
    if args.first().is_some_and(|arg| arg == "--hang-init") {
        std::fs::write(&args[1], std::process::id().to_string())?;
        std::future::pending::<()>().await;
    }
    if args.first().is_some_and(|arg| arg == "--exit-before-init") {
        std::process::exit(23);
    }
    if args.first().is_some_and(|arg| arg == "--malformed-init") {
        use tokio::io::AsyncWriteExt;
        let mut stdout = tokio::io::stdout();
        stdout.write_all(b"{malformed MCP frame}\n").await?;
        stdout.flush().await?;
        std::future::pending::<()>().await;
    }
    if args.first().is_some_and(|arg| arg == "--delay-init") {
        tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    }
    let server = Fixture::new("stdio:")
        .serve(rmcp::transport::stdio())
        .await?;
    server.waiting().await?;
    Ok(())
}
