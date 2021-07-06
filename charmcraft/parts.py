# Copyright 2020-2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# For further info, check https://github.com/canonical/charmcraft

"""Integration with craft-parts."""

import pathlib
import shlex
import subprocess
from typing import Any, Dict, List, cast

from craft_parts import LifecycleManager, Step, plugins
from xdg import BaseDirectory  # type: ignore

from charmcraft.config import Config


class CharmPluginProperties(plugins.PluginProperties, plugins.PluginModel):
    """Parameters used in charm building."""

    source: str = ""
    charm_requirements: List[str] = []
    charm_python_packages: List[str] = []

    @classmethod
    def unmarshal(cls, data: Dict[str, Any]):
        plugin_data = plugins.extract_plugin_properties(
            data, plugin_name="charm", required=["source"]
        )
        return cls(**plugin_data)


class CharmPlugin(plugins.Plugin):
    """Build the charm."""

    properties_class = CharmPluginProperties

    @classmethod
    def get_build_snaps(self):
        """Return a set of required snaps to install in the build environment."""
        return set()

    def get_build_packages(self):
        """Return a set of required packages to install in the build environment."""
        return {"findutils", "python3-dev", "python3-venv"}

    def get_build_environment(self):
        """Return a dictionary with the environment to use in the build step."""
        plugin_venv_dir = self._part_info.work_dir / "venv"
        venv_dir = self._part_info.part_install_dir / self._part_info.venv_dir
        return {
            # Add PATH to the python interpreter we always intend to use with
            # this plugin. It can be user overridden, but that is an explicit
            # choice made by a user.
            "PATH": "{}/bin:{}/bin:${{PATH}}".format(str(venv_dir), str(plugin_venv_dir)),
        }

    def get_build_commands(self):
        """Return a list of commands to run during the build step."""
        plugin_venv_dir = self._part_info.work_dir / "venv"
        venv_dir = self._part_info.part_install_dir / self._part_info.venv_dir
        pip_install_cmd = f"pip3 install --target={venv_dir} --no-binary :all:"
        commands = [
            'python3 -m venv "{}"'.format(plugin_venv_dir),
            "pip install -U pip setuptools wheel",
        ]

        if _pip_needs_system():
            logger.debug("adding --system to work around pip3 defaulting to --user")
            pip_install_cmd += "--system"

        options = cast(CharmPluginProperties, self._options)

        if options.charm_python_packages:
            python_packages = " ".join(
                [shlex.quote(pkg) for pkg in options.charm_python_packages]
            )
            python_packages_cmd = f"{pip_install_cmd} -U {python_packages}"
            commands.append(python_packages_cmd)

        if options.charm_requirements:
            requirements = " ".join(f"-r {r!r}" for r in options.charm_requirements)
            requirements_cmd = f"{pip_install_cmd} -U {requirements}"
            commands.append(requirements_cmd)

        install_dir = self._part_info.part_install_dir
        commands.append(
            'cp --archive --link --no-dereference . "{}"'.format(install_dir)
        )

        return commands

def _pip_needs_system():
    """Determine whether pip3 defaults to --user, needing --system to turn it off."""
    cmd = [
        "python3",
        "-c",
        (
            "from pip.commands.install import InstallCommand; "
            'assert InstallCommand().cmd_opts.get_option("--system") is not None'
        ),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def register_charm_plugin():
    plugins.register({"charm": CharmPlugin})


def process_parts(
    partdef: Dict[str, Any],
    *,
    entrypoint: str,
    work_dir: pathlib.Path,
    venv_dir: pathlib.Path,
    config: Config,
) -> pathlib.Path:
    # set the cache dir for parts package management
    cache_dir = BaseDirectory.save_cache_path("charmcraft")

    lcm = LifecycleManager(
        {"parts": partdef},
        application_name="charmcraft",
        work_dir=work_dir,
        cache_dir=cache_dir,
        entrypoint=entrypoint,
        venv_dir=venv_dir,
        config=config,
    )

    actions = lcm.plan(Step.PRIME)
    with lcm.action_executor() as aex:
        aex.execute(actions)

    return lcm.project_info.prime_dir
