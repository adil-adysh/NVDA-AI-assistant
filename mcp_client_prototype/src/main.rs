#[tokio::main]
async fn main() {
    if let Err(error) = mcp_client_prototype::run_stdio().await {
        eprintln!("manager stopped: {error}");
        std::process::exit(1);
    }
}
