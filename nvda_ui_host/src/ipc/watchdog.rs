use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

static LAST_ACTIVITY_SECS: AtomicU64 = AtomicU64::new(0);

/// Record activity — call when a command client connects or disconnects.
pub(crate) fn touch() {
	let now = SystemTime::now()
		.duration_since(UNIX_EPOCH)
		.unwrap_or_default()
		.as_secs();
	LAST_ACTIVITY_SECS.store(now, Ordering::SeqCst);
}

/// Spawn a watchdog thread that posts WM_QUIT to the main thread when
/// no command client has connected for `idle_minutes` minutes.
#[allow(dead_code)] // called from main.rs binary, not lib.rs
pub fn start(main_thread_id: u32, idle_minutes: u64) {
	let idle_secs = idle_minutes * 60;
	touch(); // seed the initial timestamp
	thread::spawn(move || loop {
		thread::sleep(Duration::from_secs(30));
		let last = LAST_ACTIVITY_SECS.load(Ordering::SeqCst);
		let now = SystemTime::now()
			.duration_since(UNIX_EPOCH)
			.unwrap_or_default()
			.as_secs();
		if last > 0 && now.saturating_sub(last) >= idle_secs {
			crate::logger::info(&format!(
				"Idle timeout reached after {} minutes, exiting host process",
				idle_minutes
			));
			// Post WM_QUIT (18) to the main thread's message queue so the
			// message loop exits naturally and CoUninitialize runs.
			#[allow(unused)]
			#[link(name = "user32")]
			extern "system" {
				fn PostThreadMessageW(idThread: u32, Msg: u32, wParam: usize, lParam: isize) -> i32;
			}
			unsafe {
				PostThreadMessageW(main_thread_id, 18, 0, 0);
			}
			break;
		}
	});
}
