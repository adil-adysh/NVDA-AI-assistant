use std::fs::{File, OpenOptions};
use std::io::{self, Write};
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

static LOG_FILE: OnceLock<Mutex<File>> = OnceLock::new();

pub fn init() {
    let primary_log_path = determine_log_path();
    if let Some(parent) = primary_log_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    let log_path = if OpenOptions::new().create(true).append(true).open(&primary_log_path).is_ok() {
        primary_log_path
    } else {
        std::env::temp_dir().join("nvda_ui_host.log")
    };

    if let Ok(file) = OpenOptions::new().create(true).append(true).open(&log_path) {
        let _ = LOG_FILE.set(Mutex::new(file));
        let _ = write_line("INFO", &format!("Log initialized at {}", log_path.display()));
    } else {
        let _ = write_line("WARN", "Unable to open log file; falling back to console only");
    }
}

fn determine_log_path() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        let mut path = PathBuf::from(appdata);
        path.push("nvda");
        path.push("AIAssistant");
        path.push("nvda_ui_host.log");
        return path;
    }

    if let Ok(mut exe_path) = std::env::current_exe() {
        exe_path.pop();
        exe_path.push("nvda_ui_host.log");
        return exe_path;
    }

    std::env::current_dir()
        .map(|mut dir| {
            dir.push("nvda_ui_host.log");
            dir
        })
        .unwrap_or_else(|_| std::env::temp_dir().join("nvda_ui_host.log"))
}

pub fn log_file_path() -> PathBuf {
    determine_log_path()
}

fn timestamp() -> String {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    format!("{:010}.{:03}", now.as_secs(), now.subsec_millis())
}

fn write_line(level: &str, message: &str) -> io::Result<()> {
    let line = format!("{} [{}] {}\n", timestamp(), level, message);
    if let Some(mutex) = LOG_FILE.get() {
        if let Ok(mut file) = mutex.lock() {
            let _ = file.write_all(line.as_bytes());
            let _ = file.flush();
        }
    }

    match level {
        "ERROR" | "WARN" => {
            let _ = io::stderr().write_all(line.as_bytes());
        }
        _ => {
            let _ = io::stdout().write_all(line.as_bytes());
        }
    }
    Ok(())
}

pub fn info(message: &str) {
    let _ = write_line("INFO", message);
}

pub fn debug(message: &str) {
    let _ = write_line("DEBUG", message);
}

pub fn preview(message: &str, limit: usize) -> String {
    let mut preview = String::new();
    for character in message.chars().take(limit) {
        preview.push(character);
    }
    if message.chars().count() > limit {
        preview.push_str("...");
    }
    preview
}

pub fn warn(message: &str) {
    let _ = write_line("WARN", message);
}

pub fn error(message: &str) {
    let _ = write_line("ERROR", message);
}
