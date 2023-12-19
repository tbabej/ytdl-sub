import copy
from abc import ABC
from typing import Any
from typing import Dict
from typing import Set

from ytdl_sub.entries.script.function_scripts import CUSTOM_FUNCTION_SCRIPTS
from ytdl_sub.entries.script.variable_definitions import Variable
from ytdl_sub.entries.script.variable_scripts import UNRESOLVED_VARIABLES
from ytdl_sub.entries.script.variable_scripts import VARIABLE_SCRIPTS
from ytdl_sub.script.script import Script
from ytdl_sub.utils.script import ScriptUtils


class Scriptable(ABC):
    """
    Shared class between Entry and Overrides to manage their underlying Script.
    """

    def __init__(self):
        self.script = Script(
            ScriptUtils.add_sanitized_variables(
                dict(copy.deepcopy(VARIABLE_SCRIPTS), **copy.deepcopy(CUSTOM_FUNCTION_SCRIPTS))
            )
        )
        self.unresolvable: Set[str] = copy.deepcopy(UNRESOLVED_VARIABLES)

    def update_script(self) -> None:
        """
        Updates any potential variables to a resolvable. This is done
        to avoid re-resolving the same variables over-and-over.
        """
        self.script.resolve(unresolvable=self.unresolvable, update=True)

    def add(self, values: Dict[str | Variable, Any]) -> None:
        """
        Add new values to the script
        """
        values_as_str: Dict[str, str] = {
            (key.variable_name if isinstance(key, Variable) else key): val
            for key, val in values.items()
        }

        self.unresolvable -= set(list(values_as_str.keys()))
        self.script.add(
            ScriptUtils.add_sanitized_variables(
                {name: ScriptUtils.to_script(value) for name, value in values_as_str.items()}
            ),
            unresolvable=self.unresolvable,
        )
        self.update_script()