"""Tests for sampler learning.
"""

from gym.spaces import Box
import numpy as np
from predicators.src.sampler_learning import _create_sampler_data
from predicators.src.structs import Type, Predicate, State, Action, \
    ParameterizedOption, LiftedAtom
from predicators.src import utils


def test_create_sampler_data():
    """Tests for _create_sampler_data().
    """
    utils.update_config({"min_data_for_nsrt": 0, "seed": 123})
    # Create two partitions
    cup_type = Type("cup_type", ["feat1"])
    cup0 = cup_type("cup0")
    var_cup0 = cup_type("?cup0")
    pred0 = Predicate("Pred0", [cup_type],
                      lambda s, o: s[o[0]][0] > 0.5)
    predicates = {pred0}
    option = ParameterizedOption(
        "dummy", [], Box(0.1, 1, (1,)), lambda s, o, p: Action(p),
        lambda s, o, p: False, lambda s, o, p: False).ground(
            [], np.array([0.3]))

    # Transition 1: adds pred0(cup0)
    state = State({cup0: [0.4]})
    action = option.policy(state)
    action.set_option(option)
    next_state = State({cup0: [0.9]})
    atoms = utils.abstract(state, predicates)
    next_atoms = utils.abstract(next_state, predicates)
    add_effects = next_atoms - atoms
    delete_effects = atoms - next_atoms
    transition1 = (state, next_state, atoms, option, next_atoms,
                   add_effects, delete_effects)

    # Transition 2: does nothing
    state = State({cup0: [0.4]})
    action = option.policy(state)
    action.set_option(option)
    next_state = state
    atoms = utils.abstract(state, predicates)
    next_atoms = utils.abstract(next_state, predicates)
    add_effects = next_atoms - atoms
    delete_effects = atoms - next_atoms
    transition2 = (state, next_state, atoms, option, next_atoms,
                   add_effects, delete_effects)

    transitions = [[(transition1, {cup0: var_cup0})],
                   [(transition2, {})]]
    variables = [var_cup0]
    preconditions = set()
    add_effects = {LiftedAtom(pred0, [var_cup0])}
    delete_effects = set()
    param_option = option.parent
    partition_idx = 0

    positive_examples, negative_examples = _create_sampler_data(
        transitions, variables, preconditions, add_effects,
        delete_effects, param_option, partition_idx)
    assert len(positive_examples) == 1
    assert len(negative_examples) == 1

    # When building data for a partition with effects X, if we
    # encounter a transition with effects Y, and if Y is a superset
    # of X, then we do not want to include the transition as a
    # negative example, because if Y was achieved, then X was also
    # achieved. So for now, we just filter out such examples.
    #
    # In the example here, transition 1's effects are a superset
    # of transition 2's effects. So when creating the examples
    # for partition 2, we do not want to inclue transition 1
    # in the negative effects.
    variables = []
    add_effects = set()
    partition_idx = 1
    positive_examples, negative_examples = _create_sampler_data(
        transitions, variables, preconditions, add_effects,
        delete_effects, param_option, partition_idx)
    assert len(positive_examples) == 1
    assert len(negative_examples) == 0