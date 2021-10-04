"""Contains global, immutable settings.
Anything that varies between runs should be a command-line arg (args.py).
"""

from collections import defaultdict
from types import SimpleNamespace
from typing import Dict, Any


class GlobalSettings:
    """Unchanging settings.
    """
    # cover env parameters
    cover_num_blocks = 2
    cover_num_targets = 2
    cover_block_widths = [0.1, 0.07]
    cover_target_widths = [0.05, 0.03]

    # SeSamE parameters
    max_samples_per_step = 10
    max_num_steps_option_rollout = 100
    max_skeletons = 1  # if 1, can only solve downward refinable tasks

    @staticmethod
    def get_arg_specific_settings(args: Dict[str, Any]) -> Dict[str, Any]:
        """A workaround for global settings that are
        derived from the experiment-specific args
        """
        return dict(
            num_train_tasks=defaultdict(int, {
                "cover": 5,
            })[args["env"]],

            num_test_tasks=defaultdict(int, {
                "cover": 10,
            })[args["env"]],
        )

_attr_to_value = {}
for _attr, _value in GlobalSettings.__dict__.items():
    if _attr.startswith("_"):
        continue
    assert _attr not in _attr_to_value  # duplicate attributes
    _attr_to_value[_attr] = _value
CFG = SimpleNamespace(**_attr_to_value)