"""Contains the plugin manager object"""
from typing import List, Type, cast

import pluggy

from tox import provision
from tox.config import core as core_config
from tox.config import main as main_config
from tox.config.cli.parser import ToxParser
from tox.config.sets import ConfigSet
from tox.session import state
from tox.session.cmd import list_env, show_config, version_flag
from tox.session.cmd.run import parallel, sequential
from tox.tox_env.api import ToxEnv
from tox.tox_env.python.virtual_env import runner
from tox.tox_env.python.virtual_env.package.artifact import dev, sdist, wheel
from tox.tox_env.register import REGISTER, ToxEnvRegister

from . import NAME, spec


class Plugin:
    def __init__(self) -> None:
        self.manager: pluggy.PluginManager = pluggy.PluginManager(NAME)  # type: ignore[no-any-unimported]
        self.manager.add_hookspecs(spec)

        internal_plugins = (
            main_config,
            provision,
            core_config,
            runner,
            dev,
            sdist,
            wheel,
            parallel,
            sequential,
            list_env,
            version_flag,
            show_config,
        )

        for plugin in internal_plugins:
            self.manager.register(plugin)
        self.manager.load_setuptools_entrypoints(NAME)
        self.manager.register(state)

        REGISTER.populate(self)
        self.manager.check_pending()

    def tox_add_option(self, parser: ToxParser) -> None:
        self.manager.hook.tox_add_option(parser=parser)

    def tox_add_core_config(self, core: ConfigSet) -> None:
        self.manager.hook.tox_add_core_config(core=core)

    def tox_register_tox_env(self, register: "ToxEnvRegister") -> List[Type[ToxEnv]]:
        return cast(List[Type[ToxEnv]], self.manager.hook.tox_register_tox_env(register=register))


MANAGER = Plugin()

__all__ = (
    "MANAGER",
    "Plugin",
)
