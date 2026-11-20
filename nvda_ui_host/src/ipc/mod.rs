mod state;
mod transport;
pub(crate) mod watchdog;

pub(crate) use state::queue_ui_event;

#[cfg(test)]
pub(crate) fn pending_ui_event_count() -> usize {
	state::pending_ui_event_count()
}

pub fn start_pipe_listener() {
	transport::start_pipe_listener();
}
