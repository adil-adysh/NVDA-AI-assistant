# -*- coding: utf-8 -*-
from __future__ import annotations

import functools
from typing import Any, Callable

import queueHandler
import ui


def message(text: str) -> None:
    ui.message(text)


def browseable_message(text: str, title: str) -> None:
    ui.browseableMessage(text, title=title)


def queue(callback: Callable[..., None], *args: Any, **kwargs: Any) -> None:
    if kwargs:
        callback = functools.partial(callback, **kwargs)
    queueHandler.queueFunction(queueHandler.eventQueue, callback, *args)
