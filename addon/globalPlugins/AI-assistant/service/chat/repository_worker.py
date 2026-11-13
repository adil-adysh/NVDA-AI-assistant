"""Conversation repository port backed by worker jobs."""
from .repository import ConversationSummary
from .repository_backends import _message_to_dict, _message_from_dict
from .session import ConversationSession
from ...core.translation import _


class WorkerConversationRepository:
	requires_background = True

	def __init__(self, worker_client=None):
		self._worker_client = worker_client

	def _request(self, operation, conversation_id=None, **payload):
		client = self._worker_client
		if client is None:
			from ...plugin.worker_supervisor import get_worker_client_for_operation
			client = get_worker_client_for_operation()
		if client is None:
			raise RuntimeError(_("The local AI worker is unavailable."))
		# Persistence commits must survive cancellation of inference.
		from ...core.cancellation import cancellation_scope
		with cancellation_scope(None):
			response = client.run_job("conversation", {"operation": operation,
				"conversation_id": conversation_id, **payload}, timeout=30.0)
		if not response.get("success"):
			raise RuntimeError(response.get("error_message") or _("Unable to access saved conversations."))
		return response

	def exists(self, conversation_id):
		return bool(self._request("exists", conversation_id).get("exists"))

	def load(self, conversation_id):
		return ConversationSession(_messages=[_message_from_dict(message) for message in self._request("load", conversation_id).get("messages", [])])

	def save(self, conversation_id, messages):
		self._request("save", conversation_id, messages=[_message_to_dict(message) for message in messages])

	def list_summaries(self):
		return [ConversationSummary(conversation_id=item["id"], **{key: value for key, value in item.items() if key != "id"}) for item in self._request("list").get("summaries", [])]

	def delete(self, conversation_id):
		return bool(self._request("delete", conversation_id).get("deleted"))
