"""
初始化
"""

import threading
from functools import cached_property

from loguru import logger
from loguru._logger import Logger
from toollib.utils import Singleton

from app.initializer._conf import Config, init_config
from app.initializer._log import init_logger


class G(metaclass=Singleton):
    """
    全局变量
    """

    _init_lock = threading.Lock()
    _init_properties = (
        "config",
        "logger",
    )

    def __init__(self):
        self._initialized = False

    @cached_property
    def config(self) -> Config:
        return init_config()

    @cached_property
    def logger(self) -> Logger:
        return init_logger(
            level="INFO",
            serialize=self.config.APP_LOG_SERIALIZE,
            outdir=self.config.APP_LOG_OUTDIR,
        )

    def setup(self):
        with self._init_lock:
            if not self._initialized:
                for prop_name in self._init_properties:
                    if hasattr(self, prop_name):
                        getattr(self, prop_name)
                    else:
                        logger.warning(f"{prop_name} not found")
                self._initialized = True


g = G()
