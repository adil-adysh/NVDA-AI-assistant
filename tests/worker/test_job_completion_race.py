"""A fast job can finish on the event pipe before its command acknowledgement."""

import threading

from tests.support import load_addon_module

module = load_addon_module("service.worker_client", namespace="job_completion_race_tests")
dto = load_addon_module("core.job.dto", namespace="job_completion_race_tests")


def test_submission_ack_preserves_completed_snapshot():
	closed = threading.Event()
	class EventPipe:
		is_connected = True
		def read_frame(self):
			closed.wait()
			raise module.PipeDisconnectedError("closed")

	class CommandPipe:
		def write_frame(self, frame):
			jobs._handle_event_frame(dto.JobResult(
				job_id=frame["job_id"], status=dto.JobStatus.COMPLETED,
				result_data={"answer": 42}, generation=1,
			).to_dict())

		def read_frame(self):
			return {"type": "job_ack", "status": "accepted"}

	jobs = module.NamedPipeJobClient(CommandPipe(), EventPipe())
	try:
		job_id = jobs.submit_job(dto.JobSpec(job_id="fast-job", job_type="echo"))
		snapshot = jobs.get_job_snapshot(job_id)
		assert snapshot.is_terminal
		assert snapshot.result.result_data == {"answer": 42}
		assert jobs.list_active_jobs() == ()
	finally:
		jobs.close()
		closed.set()
		jobs._evt_listener_thread.join(timeout=1)
