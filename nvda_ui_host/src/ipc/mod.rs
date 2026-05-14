mod state;
mod transport;
pub(crate) mod watchdog;

pub(crate) use state::queue_ui_event;

pub fn start_pipe_listener() {
	transport::start_pipe_listener();
}
