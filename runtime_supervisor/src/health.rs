use serde_json::Value;
use std::time::Duration;

pub trait HealthChecker: Send + Sync {
    fn check_health(&self, base_url: &str, timeout: Duration) -> bool;
    fn check_compatible(&self, base_url: &str, timeout: Duration) -> bool;
}

pub struct UreqHealthChecker;

impl HealthChecker for UreqHealthChecker {
    fn check_health(&self, base_url: &str, timeout: Duration) -> bool {
        let url = format!("{}/v1/models", base_url.trim_end_matches('/'));
        let agent = ureq::builder()
            .timeout_connect(timeout)
            .timeout_read(timeout)
            .timeout_write(timeout)
            .build();
        match agent.get(&url).call() {
            Ok(resp) => resp.status() == 200,
            Err(_) => {
                // Fallback to /models (llama-server sometimes exposes /models)
                let alt_url = format!("{}/models", base_url.trim_end_matches('/'));
                match agent.get(&alt_url).call() {
                    Ok(resp) => resp.status() == 200,
                    Err(_) => false,
                }
            }
        }
    }

    fn check_compatible(&self, base_url: &str, timeout: Duration) -> bool {
        let url = format!("{}/v1/models", base_url.trim_end_matches('/'));
        let agent = ureq::builder()
            .timeout_connect(timeout)
            .timeout_read(timeout)
            .timeout_write(timeout)
            .build();
        let resp = match agent.get(&url).call() {
            Ok(r) => r,
            Err(_) => {
                let alt_url = format!("{}/models", base_url.trim_end_matches('/'));
                match agent.get(&alt_url).call() {
                    Ok(r) => r,
                    Err(_) => return false,
                }
            }
        };

        if resp.status() != 200 {
            return false;
        }

        // Validate JSON structure: standard OpenAI `/v1/models` returns {"data": [...]}
        if let Ok(val) = resp.into_json::<Value>() {
            if let Some(map) = val.as_object() {
                if map.contains_key("data") || map.contains_key("models") {
                    return true;
                }
            }
        }
        false
    }
}
