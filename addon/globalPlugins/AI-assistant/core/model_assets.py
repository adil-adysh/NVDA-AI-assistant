"""Immutable worker-safe model discovery messages."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelAssetSnapshot:
	asset_id: str
	token: str
	path: str
	source: str
	availability: str
	size_bytes: int | None
	repository: str | None = None
	revision: str | None = None
	artifact: str | None = None
	quantization: str | None = None
	capabilities: tuple[str, ...] = ()
	file_identity: str = ""

	def to_dict(self):
		return asdict(self)

	@classmethod
	def from_dict(cls, value):
		fields = dict(value)
		fields["capabilities"] = tuple(fields.get("capabilities") or ())
		return cls(**fields)


@dataclass(frozen=True)
class ModelDiscoverySnapshot:
	generation: int
	assets: tuple[ModelAssetSnapshot, ...]
	errors: dict[str, str]
	scanned_at: float

	def to_dict(self):
		return asdict(self)

	@classmethod
	def from_dict(cls, value):
		return cls(int(value["generation"]), tuple(ModelAssetSnapshot.from_dict(asset) for asset in value["assets"]),
			dict(value["errors"]), float(value["scanned_at"]))
