# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import uuid


class ExecutionContext:
    def __init__(self):
        self.request_id: str = uuid.uuid4().hex
        self.start_time: float = time.time()
