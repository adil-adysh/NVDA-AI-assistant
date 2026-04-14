# -*- coding: utf-8 -*-
from __future__ import annotations

import functools
import threading
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


def call(callback: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if threading.current_thread() is threading.main_thread():
        return callback(*args, **kwargs)

    done = threading.Event()
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = callback(*args, **kwargs)
        except Exception as error:
            result["error"] = error
        finally:
            done.set()

    queueHandler.queueFunction(queueHandler.eventQueue, runner)
    done.wait()
    if "error" in result:
        raise result["error"]
    return result.get("value")
