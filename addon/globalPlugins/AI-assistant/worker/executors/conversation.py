"""Serialized persistence jobs; native database access stays outside NVDA."""
import threading

try:
	from ...service.chat.repository_backends import build_default_conversation_repository, _message_to_dict, _message_from_dict
	from ...core.job.dto import JobResult, JobStatus
except ImportError:
	from service.chat.repository_backends import build_default_conversation_repository, _message_to_dict, _message_from_dict
	from core.job.dto import JobResult, JobStatus

_repository = None
_lock = threading.Lock()


def execute_conversation_job(spec, token):
	global _repository
	acquired = False
	try:
		while not _lock.acquire(timeout=0.05):
			token.check_cancelled()
		acquired = True
		token.check_cancelled()
		if _repository is None:
			_repository = build_default_conversation_repository()
		operation = spec.payload.get("operation")
		conversation_id = str(spec.payload.get("conversation_id", ""))
		data = {"success": True}
		if operation == "exists":
			data["exists"] = _repository.exists(conversation_id)
		elif operation == "load":
			data["messages"] = [_message_to_dict(message) for message in _repository.load(conversation_id).snapshot()]
		elif operation == "save":
			_repository.save(conversation_id, [_message_from_dict(message) for message in spec.payload.get("messages", [])])
		elif operation == "list":
			data["summaries"] = [summary.to_metadata() for summary in _repository.list_summaries()]
		elif operation == "delete":
			data["deleted"] = _repository.delete(conversation_id)
		else:
			raise ValueError("Unknown conversation repository operation")
		return JobResult(job_id=spec.job_id, status=JobStatus.COMPLETED, result_data=data, generation=spec.generation)
	finally:
		if acquired:
			_lock.release()
