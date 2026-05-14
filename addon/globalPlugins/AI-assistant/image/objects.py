# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import api


def get_object_safe(source: str = "foreground") -> Any | None:
	"""Get an NVDA object by source name, returning None on failure.

	Supported sources:
	- ``"desktop"`` — full virtual desktop
	- ``"foreground"`` — foreground window
	- ``"focus"`` — keyboard focus object
	- ``"navigator"`` — NVDA navigator object
	"""
	try:
		if source == "desktop":
			return api.getDesktopObject()
		elif source == "foreground":
			return api.getForegroundObject()
		elif source == "focus":
			return api.getFocusObject()
		elif source == "navigator":
			return api.getNavigatorObject()
		else:
			return None
	except Exception:
		return None


def coerce_location_tuple(location: Any) -> tuple[int, int, int, int] | None:
	"""Coerce a location-like value to (left, top, width, height)."""
	try:
		if hasattr(location, "left"):
			left = int(location.left)
			top = int(location.top)
			width = int(location.width)
			height = int(location.height)
		else:
			left, top, width, height = (int(v) for v in location)
	except (TypeError, ValueError, AttributeError):
		return None

	if width <= 0 or height <= 0:
		return None

	return left, top, width, height


def get_object_location(obj: Any) -> tuple[int, int, int, int] | None:
	"""Get the screen location (left, top, width, height) of an NVDA object.

	Returns ``None`` if the object is not valid or has no usable location.
	"""
	try:
		validate_object_location(obj)
	except TypeError:
		return None

	location = obj.location
	if location is None:
		return None

	return coerce_location_tuple(location)


def validate_object_location(obj: Any) -> None:
	"""Validate that an NVDA object has a usable screen location.

	Raises ``TypeError`` if the object has no ``location`` attribute
	or the location is not a ``locationHelper.RectLTWH`` — matching
	the Screenshots Wizard add-on's ``fromObject`` validation.
	"""
	if not hasattr(obj, "location"):
		raise TypeError("The argument must be an NVDA object")
	from locationHelper import RectLTWH

	if not isinstance(obj.location, RectLTWH):
		raise TypeError("The location attribute must be a RectLTWH object")


def clip_location_to_containers(obj: Any, location: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
	"""Clip an object's bounding box to its visible area by intersecting
	with each parent container's location.

	Prevents capturing parts of an object that are scrolled out of view
	or extend beyond window boundaries (same technique used by the
	Screenshots Wizard add-on).
	"""
	from locationHelper import RectLTWH

	clipped = RectLTWH(*location)
	current = obj
	while current is not None:
		try:
			container = current.container
		except Exception:
			break
		if container is None:
			break
		try:
			cl = container.location
		except Exception:
			cl = None
		if cl is not None:
			try:
				container_rect = RectLTWH(
					int(cl.left), int(cl.top),
					int(cl.width), int(cl.height),
				) if hasattr(cl, "left") else RectLTWH(
					int(cl[0]), int(cl[1]),
					int(cl[2]), int(cl[3]),
				)
			except (TypeError, ValueError, IndexError):
				pass
			else:
				if container_rect != (0, 0, 0, 0):
					clipped = clipped.intersection(container_rect)
		current = container

	result = coerce_location_tuple((clipped.left, clipped.top, clipped.width, clipped.height))
	return result if result is not None else location
