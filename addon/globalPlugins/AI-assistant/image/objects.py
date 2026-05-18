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


def get_object_location_with_parent_fallback(
	obj: Any,
	max_depth: int = 8,
) -> tuple[int, int, int, int] | None:
	"""Get the screen location of an NVDA object, walking up parents if needed.

	When the leaf object (e.g. an Ia2Web element inside a WebView) has no
	location, this walks up the container hierarchy to find the nearest
	ancestor with a usable location.  The ancestor's location is returned
	unclipped so that :func:`clip_location_to_containers` can still refine it
	later.

	If the container chain yields nothing, this falls back to
	``api.getFocusAncestors()`` which returns NVDA's own tracked focus
	ancestor chain — this chain may include non-IA2 objects (UIA wrappers,
	``Window`` objects) that provide reliable bounding rectangles even when
	the IA2 tree does not.  This pattern mirrors Developer Toolkit's
	``isFocusAncestor`` validation in ``shared.py``.

	Returns ``None`` if no ancestor within *max_depth* steps has a location.
	"""
	from logHandler import log

	# Try the object itself first
	loc = get_object_location(obj)
	if loc is not None:
		return loc

	# Walk up the container chain
	current = obj
	for depth in range(max_depth):
		try:
			current = current.container
		except Exception:
			break
		if current is None:
			break
		loc = get_object_location(current)
		if loc is not None:
			log.debug(
				"Location resolved via container chain: leaf=%s depth=%d ancestor=%s loc=%s",
				type(obj).__name__,
				depth + 1,
				type(current).__name__,
				loc,
			)
			return loc

	# Fall back to NVDA's focus-ancestor chain (may include UIA / Window
	# objects that the container chain missed).  Pattern from Developer
	# Toolkit's shared.py isFocusAncestor validation.
	try:
		ancestors = api.getFocusAncestors()
	except Exception:
		ancestors = []
	for depth, ancestor in enumerate(reversed(ancestors)):
		if ancestor is obj:
			continue
		loc = get_object_location(ancestor)
		if loc is not None:
			log.debug(
				"Location resolved via focus-ancestor chain: leaf=%s depth=%d ancestor=%s loc=%s",
				type(obj).__name__,
				depth + 1,
				type(ancestor).__name__,
				loc,
			)
			return loc

	return None


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
	if result is None:
		from logHandler import log
		log.debug(
			"Container clipping reduced location to zero: raw=%s object=%s",
			location, type(obj).__name__,
		)
	return result if result is not None else location
