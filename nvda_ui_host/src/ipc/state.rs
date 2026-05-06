use std::collections::VecDeque;
use std::sync::{mpsc, Mutex, OnceLock};

use crate::logger;

struct UiEventState {
	sender: Option<mpsc::Sender<String>>,
	pending: VecDeque<String>,
}

impl UiEventState {
	fn new() -> Self {
		Self {
			sender: None,
			pending: VecDeque::new(),
		}
	}
}

static UI_EVENT_STATE: OnceLock<Mutex<UiEventState>> = OnceLock::new();

fn ui_event_state() -> &'static Mutex<UiEventState> {
	UI_EVENT_STATE.get_or_init(|| Mutex::new(UiEventState::new()))
}

pub(crate) fn queue_ui_event(message: String) {
	logger::debug(&format!(
		"IPC queue_ui_event called with payload len={} preview={}",
		message.len(),
		logger::preview(&message, 160)
	));
	let mut state = ui_event_state().lock().unwrap();
	if let Some(tx) = state.sender.as_ref() {
		if let Err(error) = tx.send(message) {
			logger::warn(&format!("IPC failed to send UI event; sender disconnected: {:?}", error));
			state.sender = None;
			state.pending.push_back(error.0);
		}
	} else {
		state.pending.push_back(message);
		logger::debug("IPC queue_ui_event queued UI event until an event client connects");
	}
}

pub(crate) fn install_ui_event_sender(sender: mpsc::Sender<String>) -> VecDeque<String> {
	let mut state = ui_event_state().lock().unwrap();
	state.sender = Some(sender);
	std::mem::take(&mut state.pending)
}

pub(crate) fn clear_ui_event_sender() {
	let mut state = ui_event_state().lock().unwrap();
	state.sender = None;
}

pub(crate) fn requeue_ui_events_after_disconnect(
	message: Option<String>,
	mut remaining: VecDeque<String>,
) {
	let mut state = ui_event_state().lock().unwrap();
	state.sender = None;
	if let Some(message) = message {
		state.pending.push_front(message);
	}
	state.pending.append(&mut remaining);
}

#[cfg(test)]
fn reset_ui_event_state() {
	let mut state = ui_event_state().lock().unwrap();
	state.sender = None;
	state.pending.clear();
}

#[cfg(test)]
mod tests {
	use super::*;

	#[test]
	fn queue_ui_event_buffers_messages_until_sender_is_available() {
		reset_ui_event_state();

		queue_ui_event("{\"event\":\"host_closed\"}".to_string());

		let state = ui_event_state().lock().unwrap();
		assert_eq!(state.pending.len(), 1);
		assert!(state.sender.is_none());
	}
}
