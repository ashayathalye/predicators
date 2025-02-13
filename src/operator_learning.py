"""Algorithms for operator learning, both structure and samplers.
"""

import functools
from dataclasses import dataclass
from collections import defaultdict
from typing import Set, Tuple, List, Sequence, FrozenSet, Callable, Dict, Any, \
    DefaultDict
import numpy as np
from predicators.src.structs import Dataset, Operator, GroundAtom, \
    ParameterizedOption, LiftedAtom, Variable, Predicate, ObjToVarSub, \
    Transition, Object, Array, State, _Option
from predicators.src import utils
from predicators.src.models import MLPClassifier, NeuralGaussianRegressor
from predicators.src.settings import CFG


def learn_operators_from_data(dataset: Dataset, predicates: Set[Predicate],
                              do_sampler_learning: bool) -> Set[Operator]:
    """Learn operators from the given dataset of transitions.
    States are abstracted using the given set of predicates.
    """
    print(f"\nLearning operators on {len(dataset)} trajectories...")

    transitions_by_option = generate_transitions(dataset, predicates)

    operators = []
    for param_option in transitions_by_option:
        option_transitions = transitions_by_option[param_option]
        option_ops = learn_operators_for_option(
            param_option, option_transitions, do_sampler_learning)
        operators.extend(option_ops)

    print("\nLearned operators:")
    for operator in operators:
        print(operator)
    print()

    return set(operators)


def generate_transitions(dataset: Dataset, predicates: Set[Predicate]
                         ) -> DefaultDict[
                             ParameterizedOption, List[Transition]]:
    """Given a dataset and predicates, go through the dataset and compute
    the abstract states. Returns a dict mapping ParameterizedOptions to a
    list of transitions.
    """
    transitions_by_option = defaultdict(list)
    for act_traj in dataset:
        states, options = utils.action_to_option_trajectory(act_traj)
        assert len(states) == len(options) + 1
        for i, option in enumerate(options):
            atoms = utils.abstract(states[i], predicates)
            next_atoms = utils.abstract(states[i+1], predicates)
            add_effects = next_atoms - atoms
            delete_effects = atoms - next_atoms
            transition = (states[i], states[i+1], atoms, option, next_atoms,
                          add_effects, delete_effects)
            transitions_by_option[option.parent].append(transition)
    return transitions_by_option


def learn_operators_for_option(option: ParameterizedOption,
                               transitions: List[Transition],
                               do_sampler_learning: bool,
                               ) -> List[Operator]:
    """Given an option and data for it, learn operators.
    """
    # Partition the data by lifted effects
    option_vars, add_effects, delete_effects, \
        partitioned_transitions = _partition_transitions(transitions)

    operators = []
    for i, part_transitions in enumerate(partitioned_transitions):
        if len(part_transitions) < CFG.min_data_for_operator:
            continue
        if not add_effects[i] and not delete_effects[i]:
            # Don't learn any operators for empty effects, since they're
            # not useful for planning or predicate invention.
            continue
        # Learn preconditions
        variables, preconditions = \
            _learn_preconditions(option_vars[i], add_effects[i],
                                 delete_effects[i], part_transitions)
        operator_name = f"{option.name}{i}"
        # Learn sampler
        if do_sampler_learning and option.params_space.shape != (0,):
            print(f"\nLearning sampler for operator {operator_name}")
            sampler = _learn_sampler(partitioned_transitions, variables,
                                     preconditions, add_effects[i],
                                     delete_effects[i], option, i)
        else:
            # Instantiate a random sampler.
            sampler = _RandomSampler(option).sampler
        # Construct Operator object
        operators.append(Operator(
            operator_name, variables, preconditions,
            add_effects[i], delete_effects[i], option, option_vars[i],
            sampler))

    return operators


def _partition_transitions(
        transitions: List[Transition]) -> Tuple[
            List[List[Variable]],
            List[Set[LiftedAtom]],
            List[Set[LiftedAtom]],
            List[List[Tuple[Transition, ObjToVarSub]]]]:
    option_args: List[List[Variable]] = []
    add_effects: List[Set[LiftedAtom]] = []
    delete_effects: List[Set[LiftedAtom]] = []
    partitions: List[List[Tuple[Transition, ObjToVarSub]]] = []
    for transition in transitions:
        _, _, _, option, _, trans_add_effects, trans_delete_effects = transition
        trans_option_args = option.objects
        for i in range(len(partitions)):
            # Try to unify this transition with existing effects
            # Note that both add and delete effects must unify
            part_option_args = option_args[i]
            part_add_effects = add_effects[i]
            part_delete_effects = delete_effects[i]
            suc, sub = _unify(frozenset(trans_add_effects),
                              frozenset(trans_delete_effects),
                              tuple(trans_option_args),
                              frozenset(part_add_effects),
                              frozenset(part_delete_effects),
                              tuple(part_option_args))
            if suc:
                # Add to this partition
                partitions[i].append((transition, sub))
                break
        # Otherwise, create a new group
        else:
            # Get new lifted effects
            objects = {o for atom in trans_add_effects |
                       trans_delete_effects for o in atom.objects}
            objects.update(option.objects)
            objects_lst = sorted(objects)
            variables = [Variable(f"?x{i}", o.type)
                         for i, o in enumerate(objects_lst)]
            sub = dict(zip(objects_lst, variables))
            option_args.append([sub[v] for v in trans_option_args])
            add_effects.append({atom.lift(sub) for atom
                                in trans_add_effects})
            delete_effects.append({atom.lift(sub) for atom
                                   in trans_delete_effects})
            new_partition = [(transition, sub)]
            partitions.append(new_partition)

    assert len(option_args) == len(add_effects) == \
           len(delete_effects) == len(partitions)
    return option_args, add_effects, delete_effects, partitions


def  _learn_preconditions(option_vars: List[Variable],
        add_effects: Set[LiftedAtom], delete_effects: Set[LiftedAtom],
        transitions: List[Tuple[Transition, ObjToVarSub]]) -> Tuple[
            Sequence[Variable], Set[LiftedAtom]]:
    for i, ((_, _, atoms, option, _, trans_add_effects,
             trans_delete_effects), _) in enumerate(transitions):
        suc, sub = _unify(
            frozenset(trans_add_effects),
            frozenset(trans_delete_effects),
            tuple(option.objects),
            frozenset(add_effects),
            frozenset(delete_effects),
            tuple(option_vars))
        assert suc  # else this transition won't be in this partition
        # Remove atoms from the state which contain objects not mentioned
        # in the effects or option. This cannot handle actions at a distance.
        objects = {o for atom in trans_add_effects |
                   trans_delete_effects for o in atom.objects}
        objects.update(option.objects)
        atoms = {atom for atom in atoms if
                 all(o in objects for o in atom.objects)}
        lifted_atoms = {atom.lift(sub) for atom in atoms}
        if i == 0:
            variables = sorted(set(sub.values()))
        else:
            assert variables == sorted(set(sub.values()))
        if i == 0:
            preconditions = lifted_atoms
        else:
            preconditions &= lifted_atoms

    return variables, preconditions


@functools.lru_cache(maxsize=None)
def _unify(
        ground_add_effects: FrozenSet[GroundAtom],
        ground_delete_effects: FrozenSet[GroundAtom],
        ground_option_args: Tuple[Object, ...],
        lifted_add_effects: FrozenSet[LiftedAtom],
        lifted_delete_effects: FrozenSet[LiftedAtom],
        lifted_option_args: Tuple[Variable, ...]
) -> Tuple[bool, ObjToVarSub]:
    """Wrapper around utils.unify() that handles option arguments, add effects,
    and delete effects. Changes predicate names so that all are treated
    differently by utils.unify().
    """
    opt_arg_pred = Predicate("OPT-ARGS",
                             [a.type for a in ground_option_args],
                             _classifier=lambda s, o: False)  # dummy
    f_ground_option_args = frozenset({GroundAtom(opt_arg_pred,
                                                 ground_option_args)})
    new_ground_add_effects = utils.wrap_atom_predicates_ground(
        ground_add_effects, "ADD-")
    f_new_ground_add_effects = frozenset(new_ground_add_effects)
    new_ground_delete_effects = utils.wrap_atom_predicates_ground(
        ground_delete_effects, "DEL-")
    f_new_ground_delete_effects = frozenset(new_ground_delete_effects)

    f_lifted_option_args = frozenset({LiftedAtom(opt_arg_pred,
                                                 lifted_option_args)})
    new_lifted_add_effects = utils.wrap_atom_predicates_lifted(
        lifted_add_effects, "ADD-")
    f_new_lifted_add_effects = frozenset(new_lifted_add_effects)
    new_lifted_delete_effects = utils.wrap_atom_predicates_lifted(
        lifted_delete_effects, "DEL-")
    f_new_lifted_delete_effects = frozenset(new_lifted_delete_effects)
    return utils.unify(
        f_ground_option_args | f_new_ground_add_effects | \
            f_new_ground_delete_effects,
        f_lifted_option_args | f_new_lifted_add_effects | \
            f_new_lifted_delete_effects)


def _create_sampler_data(
        transitions: List[List[Tuple[Transition, ObjToVarSub]]],
        variables: Sequence[Variable],
        preconditions: Set[LiftedAtom],
        add_effects: Set[LiftedAtom],
        delete_effects: Set[LiftedAtom],
        param_option: ParameterizedOption,
        partition_idx: int) -> Tuple[List[Tuple[State,
                                     Dict[Variable, Object], _Option]], ...]:
    """Generate positive and negative data for training a sampler.
    """
    positive_data = []
    negative_data = []
    for idx, part_transitions in enumerate(transitions):
        for ((state, _, _, option, _, trans_add_effects, trans_delete_effects),
             obj_to_var) in part_transitions:
            assert option.parent == param_option
            var_types = [var.type for var in variables]
            objects = list(state)
            for grounding in utils.get_object_combinations(
                    objects, var_types, allow_duplicates=False):
                # If we are currently at the partition that we're learning a
                # sampler for, and this datapoint matches the actual grounding,
                # add it to the positive data and continue.
                if idx == partition_idx:
                    var_to_obj = {v: k for k, v in obj_to_var.items()}
                    actual_grounding = [var_to_obj[var] for var in variables]
                    if grounding == actual_grounding:
                        assert all(pre.predicate.holds(
                            state, [var_to_obj[v] for v in pre.variables])
                                   for pre in preconditions)
                        positive_data.append((state, var_to_obj, option))
                        continue
                sub = dict(zip(variables, grounding))
                # When building data for a partition with effects X, if we
                # encounter a transition with effects Y, and if Y is a superset
                # of X, then we do not want to include the transition as a
                # negative example, because if Y was achieved, then X was also
                # achieved. So for now, we just filter out such examples.
                ground_add_effects = {e.ground(sub) for e in add_effects}
                ground_delete_effects = {e.ground(sub) for e in delete_effects}
                if ground_add_effects.issubset(trans_add_effects) and \
                   ground_delete_effects.issubset(trans_delete_effects):
                    continue
                # Add this datapoint to the negative data.
                negative_data.append((state, sub, option))
    print(f"Generated {len(positive_data)} positive and {len(negative_data)} "
          f"negative examples")
    assert len(positive_data) == len(transitions[partition_idx])
    return positive_data, negative_data


def _learn_sampler(transitions: List[List[Tuple[Transition, ObjToVarSub]]],
                   variables: Sequence[Variable],
                   preconditions: Set[LiftedAtom],
                   add_effects: Set[LiftedAtom],
                   delete_effects: Set[LiftedAtom],
                   param_option: ParameterizedOption,
                   partition_idx: int) -> Callable[[
                       State, np.random.Generator, Sequence[Object]], Array]:
    """Learn a sampler given data. Transitions are partitioned, so
    that they can be used for generating negative data. Integer partition_idx
    represents the index into transitions corresponding to the partition that
    this sampler is being learned for.
    """
    positive_data, negative_data = _create_sampler_data(
        transitions, variables, preconditions, add_effects, delete_effects,
        param_option, partition_idx)

    # Fit classifier to data
    print("Fitting classifier...")
    X_classifier: List[List[Array]] = []
    for state, sub, option in positive_data + negative_data:
        # input is state features and option parameters
        X_classifier.append([np.array(1.0)])  # start with bias term
        for var in variables:
            X_classifier[-1].extend(state[sub[var]])
        X_classifier[-1].extend(option.params)
    X_arr_classifier = np.array(X_classifier)
    # output is binary signal
    y_arr_classifier = np.array([1 for _ in positive_data] +
                                [0 for _ in negative_data])
    classifier = MLPClassifier(X_arr_classifier.shape[1],
                               CFG.classifier_max_itr_sampler)
    classifier.fit(X_arr_classifier, y_arr_classifier)

    # Fit regressor to data
    print("Fitting regressor...")
    X_regressor: List[List[Array]] = []
    Y_regressor = []
    for state, sub, option in positive_data:  # don't use negative data!
        # input is state features
        X_regressor.append([np.array(1.0)])  # start with bias term
        for var in variables:
            X_regressor[-1].extend(state[sub[var]])
        # output is option parameters
        Y_regressor.append(option.params)
    X_arr_regressor = np.array(X_regressor)
    Y_arr_regressor = np.array(Y_regressor)
    regressor = NeuralGaussianRegressor()
    regressor.fit(X_arr_regressor, Y_arr_regressor)

    # Construct and return sampler
    return _LearnedSampler(classifier, regressor, variables,
                           param_option).sampler


@dataclass(frozen=True, eq=False, repr=False)
class _LearnedSampler:
    """A convenience class for holding the models underlying a learned sampler.
    Prefer to use this because it is pickleable.
    """
    _classifier: MLPClassifier
    _regressor: NeuralGaussianRegressor
    _variables: Sequence[Variable]
    _param_option: ParameterizedOption

    def sampler(self, state: State, rng: np.random.Generator,
                objects: Sequence[Object]) -> Array:
        """The sampler corresponding to the given models. May be used
        as the _sampler field in an Operator.
        """
        x_lst : List[Any] = [1.0]  # start with bias term
        sub = dict(zip(self._variables, objects))
        for var in self._variables:
            x_lst.extend(state[sub[var]])
        x = np.array(x_lst)
        num_rejections = 0
        while num_rejections <= CFG.max_rejection_sampling_tries:
            params = np.array(self._regressor.predict_sample(x, rng),
                              dtype=self._param_option.params_space.dtype)
            if self._param_option.params_space.contains(params) and \
               self._classifier.classify(np.r_[x, params]):
                break
            num_rejections += 1
        else:
            # Edge case: we exceeded the number of sampling tries
            # and we might be left with a params that is not in
            # bounds. If so, fall back to sampling from the space.
            if not self._param_option.params_space.contains(params):
                params = self._param_option.params_space.sample()
        return params


@dataclass(frozen=True, eq=False, repr=False)
class _RandomSampler:
    """A convenience class for implementing a random sampler. Prefer
    to use this over a lambda function because it is pickleable.
    """
    _param_option: ParameterizedOption

    def sampler(self, state: State, rng: np.random.Generator,
                objects: Sequence[Object]) -> Array:
        """A random sampler for this option. Ignores all arguments.
        """
        del state, rng, objects  # unused
        return self._param_option.params_space.sample()
