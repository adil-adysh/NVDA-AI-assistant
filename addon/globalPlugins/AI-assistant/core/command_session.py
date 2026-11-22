"""Pure command-layer ownership and stable paginated choices."""
from dataclasses import dataclass
from enum import Enum


class Phase(Enum):
	IDLE = "idle"
	COMMANDS = "commands"
	LOADING_CHOICES = "loadingChoices"
	CHOOSING = "choosing"


@dataclass(frozen=True)
class Choice:
	id: str
	label: str


class CommandSession:
	def __init__(self):
		self.phase = Phase.IDLE
		self.generation = 0
		self.provider = None
		self.choices = ()
		self.page = 0
		self.closed = False

	def activate(self):
		self.dismiss()
		if not self.closed:
			self.phase = Phase.COMMANDS

	def dismiss(self):
		self.generation += 1
		self.phase = Phase.IDLE
		self.provider = None
		self.choices = ()
		self.page = 0

	def close(self):
		self.closed = True
		self.dismiss()

	def begin_choices(self, provider):
		self.generation += 1
		self.provider = provider
		self.choices = ()
		self.page = 0
		if not self.closed:
			self.phase = Phase.LOADING_CHOICES
		return self.generation

	def accepts(self, token, provider):
		return (not self.closed and self.phase in (Phase.LOADING_CHOICES, Phase.CHOOSING)
			and self.generation == token and self.provider == provider)

	def set_choices(self, token, provider, choices):
		if not self.accepts(token, provider):
			return False
		self.choices = tuple(choices)
		self.phase = Phase.CHOOSING
		return True

	@property
	def visible_choices(self):
		return self.choices[self.page * 10:(self.page + 1) * 10]

	def choice(self, digit):
		index = 9 if digit == 0 else digit - 1
		return self.visible_choices[index] if 0 <= index < len(self.visible_choices) else None

	def move_page(self, direction):
		self.page = max(0, min(self.page + direction, max(0, (len(self.choices) - 1) // 10)))
