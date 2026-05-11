use std::fs::{remove_file, rename, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

static LOG_FILE: OnceLock<Mutex<Option<File>>> = OnceLock::new();
static LOG_PATH: OnceLock<PathBuf> = OnceLock::new();
const MAX_LOG_FILE_BYTES: u64 = 10 * 1024 * 1024;
const MAX_ROTATED_FILES: usize = 5;

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

    let _ = LOG_PATH.set(log_path.clone());

    if let Ok(file) = open_log_file(&log_path) {
        let log_file_mutex = LOG_FILE.get_or_init(|| Mutex::new(None));
        {
            let mut guard = log_file_mutex.lock().unwrap();
            *guard = Some(file);
        }

        if let Err(error) = rotate_if_needed(&log_path) {
            let _ = io::stderr().write_all(format!("Rotation failed during init: {}\n", error).as_bytes());
        }

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

fn open_log_file(path: &Path) -> io::Result<File> {
    OpenOptions::new().create(true).append(true).open(path)
}

fn current_log_path() -> PathBuf {
    LOG_PATH
        .get()
        .cloned()
        .unwrap_or_else(determine_log_path)
}

fn rotate_if_needed(log_path: &Path) -> io::Result<()> {
    if let Some(mutex) = LOG_FILE.get() {
        let mut guard = mutex.lock().unwrap();
        if let Some(file) = guard.as_ref() {
            let metadata = file.metadata()?;
            if metadata.len() >= MAX_LOG_FILE_BYTES {
                rotate_log_files(log_path, &mut *guard)?;
            }
        }
    }
    Ok(())
}

fn rotate_log_files(log_path: &Path, guard: &mut Option<File>) -> io::Result<()> {
    let old_file = guard.take();
    drop(old_file);

    for index in (1..=MAX_ROTATED_FILES).rev() {
        let existing = rotated_path(log_path, index);
        if existing.exists() {
            if index == MAX_ROTATED_FILES {
                remove_file(&existing)?;
            } else {
                let next = rotated_path(log_path, index + 1);
                rename(&existing, &next)?;
            }
        }
    }

    let first_rotated = rotated_path(log_path, 1);
    if log_path.exists() {
        rename(log_path, &first_rotated)?;
    }

    let new_file = open_log_file(log_path)?;
    *guard = Some(new_file);
    Ok(())
}

fn rotated_path(log_path: &Path, index: usize) -> PathBuf {
    let file_name = log_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("nvda_ui_host.log");
    let mut rotated = log_path.to_path_buf();
    rotated.set_file_name(format!("{}.{}", file_name, index));
    rotated
}

fn timestamp() -> String {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    format!("{:010}.{:03}", now.as_secs(), now.subsec_millis())
}

fn write_line(level: &str, message: &str) -> io::Result<()> {
    let line = format!("{} [{}] {}\n", timestamp(), level, message);
    let log_path = current_log_path();

    if let Err(error) = rotate_if_needed(&log_path) {
        let _ = io::stderr().write_all(format!("Rotation failed: {}\n", error).as_bytes());
    }

    if let Some(mutex) = LOG_FILE.get() {
        if let Ok(mut guard) = mutex.lock() {
            if let Some(file) = guard.as_mut() {
                let _ = file.write_all(line.as_bytes());
                let _ = file.flush();
            }
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
