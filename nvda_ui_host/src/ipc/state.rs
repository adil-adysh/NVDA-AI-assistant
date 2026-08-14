use std::collections::VecDeque;
use std::sync::{mpsc, Mutex, OnceLock};

use crate::logger;

struct UiEventState {
	sender: Option<mpsc::SyncSender<String>>,
	pending: VecDeque<String>,
}

const MAX_PENDING_UI_EVENTS: usize = 256;

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

fn push_pending(state: &mut UiEventState, message: String) {
	if state.pending.len() >= MAX_PENDING_UI_EVENTS {
		let _ = state.pending.pop_front();
		logger::warn(&format!(
			"IPC pending UI event queue full; dropping oldest event (capacity={})",
			MAX_PENDING_UI_EVENTS
		));
	}
	state.pending.push_back(message);
}

pub(crate) fn queue_ui_event(message: String) {
	logger::debug(&format!(
		"IPC queue_ui_event called with payload len={} preview={}",
		message.len(),
		logger::preview(&message, 160)
	));
	let mut state = ui_event_state().lock().unwrap();
	if let Some(tx) = state.sender.as_ref() {
		match tx.try_send(message) {
			Ok(()) => {}
			Err(mpsc::TrySendError::Full(message)) => {
				logger::warn("IPC event channel full; buffering UI event for reconnect");
				push_pending(&mut state, message);
			}
			Err(mpsc::TrySendError::Disconnected(message)) => {
				logger::warn("IPC UI event sender disconnected");
				state.sender = None;
				push_pending(&mut state, message);
			}
		}
	} else {
		push_pending(&mut state, message);
		logger::debug("IPC queue_ui_event queued UI event until an event client connects");
	}
}

pub(crate) fn install_ui_event_sender(sender: mpsc::SyncSender<String>) -> VecDeque<String> {
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
		if state.pending.len() >= MAX_PENDING_UI_EVENTS {
			let _ = state.pending.pop_back();
			logger::warn(&format!(
				"IPC pending UI event queue full while reconnecting; dropping oldest queued event (capacity={})",
				MAX_PENDING_UI_EVENTS
			));
		}
		state.pending.push_front(message);
	}
	while let Some(queued) = remaining.pop_front() {
		push_pending(&mut state, queued);
	}
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

		queue_ui_event("{\"event\":\"close_host\"}".to_string());

		let state = ui_event_state().lock().unwrap();
		assert_eq!(state.pending.len(), 1);
		assert!(state.sender.is_none());
	}
}
