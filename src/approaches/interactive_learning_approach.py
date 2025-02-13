"""An approach that learns predicates from a teacher.
"""

import itertools
from typing import Set, Callable, List, Collection
import numpy as np
from gym.spaces import Box
from predicators.src import utils
from predicators.src.approaches import OperatorLearningApproach, \
    ApproachTimeout, ApproachFailure
from predicators.src.structs import State, Predicate, ParameterizedOption, \
    Type, Task, Action, Dataset, GroundAtom, ActionTrajectory
from predicators.src.models import LearnedPredicateClassifier, MLPClassifier
from predicators.src.utils import get_object_combinations, strip_predicate
from predicators.src.settings import CFG


class InteractiveLearningApproach(OperatorLearningApproach):
    """An approach that learns predicates from a teacher.
    """
    def __init__(self, simulator: Callable[[State, Action], State],
                 all_predicates: Set[Predicate],
                 initial_options: Set[ParameterizedOption],
                 types: Set[Type],
                 action_space: Box,
                 train_tasks: List[Task]) -> None:
        # Only the teacher is allowed to know about the initial predicates
        self._known_predicates = {p for p in all_predicates
                                  if p.name in CFG.interactive_known_predicates}
        predicates_to_learn = all_predicates - self._known_predicates
        self._teacher = _Teacher(all_predicates, predicates_to_learn)
        # All seen data
        self._dataset: List[ActionTrajectory] = []
        self._ground_atom_dataset: List[List[Set[GroundAtom]]] = []
        # No cheating!
        self._predicates_to_learn = {strip_predicate(p)
                                     for p in predicates_to_learn}
        del all_predicates
        del predicates_to_learn
        super().__init__(simulator, self._predicates_to_learn, initial_options,
                         types, action_space, train_tasks)

    def _get_current_predicates(self) -> Set[Predicate]:
        return self._known_predicates | self._predicates_to_learn

    def _load_dataset(self, dataset: Dataset) -> None:
        """Stores dataset and corresponding ground atom dataset."""
        ground_atom_data = self._teacher.generate_data(dataset)
        self._dataset.extend(dataset)
        self._ground_atom_dataset.extend(ground_atom_data)

    def learn_from_offline_dataset(self, dataset: Dataset) -> None:
        self._load_dataset(dataset)
        # Learn predicates and operators
        self._relearn_predicates_and_operators()
        # Active learning
        new_trajectories: Dataset = []
        for i in range(1, CFG.interactive_num_episodes+1):
            print(f"\nActive learning episode {i}")
            # Sample initial state from train tasks
            index = self._rng.choice(len(self._train_tasks))
            state = self._train_tasks[index].init
            # Find policy for exploration
            task_list = glib_sample(state, self._get_current_predicates(),
                                    self._ground_atom_dataset)
            assert task_list
            task = task_list[0]
            for task in task_list:
                try:
                    print("Solving for policy...")
                    policy = self.solve(task, timeout=CFG.timeout)
                    break
                except (ApproachTimeout, ApproachFailure) \
                        as e:  # pragma: no cover
                    print(f"Approach failed to solve with error: {e}")
                    continue
            else:  # No policy found
                raise ApproachFailure("Failed to sample a task that approach "
                                      "can solve.")  # pragma: no cover
            # Roll out policy
            action_traj, _, _ = utils.run_policy_on_task(
                                    policy, task, self._simulator,
                                    self._get_current_predicates(),
                                    max_steps=CFG.interactive_max_steps)
            new_trajectories.append(action_traj)
            if i % CFG.interactive_relearn_every == 0:
                print("Asking teacher...")
                # Update dataset
                self._dataset.extend(new_trajectories)
                # Pick a state from the new states explored
                for s in self._get_states_to_ask(new_trajectories):
                    # For now, pick a random ground atom to ask about
                    ground_atoms = utils.all_possible_ground_atoms(
                                            s, self._get_current_predicates())
                    idx = self._rng.choice(len(ground_atoms))
                    random_atom = ground_atoms[idx]
                    if self._ask_teacher(s, random_atom):
                        # Add this atom if it's a positive example
                        self._ground_atom_dataset.append([{random_atom}])
                        # Add corresponding "action trajectory" to dataset
                        self._dataset.append(([s], []))
                    # Still need to implement a way to use negative examples
                # Relearn predicates and operators
                self._relearn_predicates_and_operators()
                # Reset trajectories list
                new_trajectories = []


    def _relearn_predicates_and_operators(self) -> None:
        """Learns predicates and operators in a semi-supervised fashion.
        """
        print("\nStarting semi-supervised learning...")
        # Learn predicates
        for pred in self._predicates_to_learn:
            assert pred not in self._known_predicates
            positive_examples = []
            negative_examples = []
            # Positive examples
            for i, trajectory in enumerate(self._ground_atom_dataset):
                for j, ground_atom_set in enumerate(trajectory):
                    state = self._dataset[i][0][j]
                    positives = [state.vec(ground_atom.objects)
                                 for ground_atom in ground_atom_set
                                 if ground_atom.predicate == pred]
                    positive_examples.extend(positives)
            # Negative examples - assume unlabeled is negative for now
            for (ss, _) in self._dataset:
                for state in ss:
                    possible = [state.vec(choice)
                                for choice in get_object_combinations(
                                                  list(state),
                                                  pred.types,
                                                  allow_duplicates=False)]
                    negatives = []
                    for (ex, pos) in itertools.product(possible,
                                                       positive_examples):
                        if np.array_equal(ex, pos):
                            break
                    else:
                        # It's not a positive example
                        negatives.append(ex)
                    negative_examples.extend(negatives)
            print(f"Generated {len(positive_examples)} positive and "
                  f"{len(negative_examples)} negative examples for "
                  f"predicate {pred}")

            # Train MLP
            X = np.array(positive_examples + negative_examples)
            Y = np.array([1 for _ in positive_examples] +
                         [0 for _ in negative_examples])
            model = MLPClassifier(X.shape[1], CFG.classifier_max_itr_predicate)
            model.fit(X, Y)

            # Construct classifier function, create new Predicate, and save it
            classifier = LearnedPredicateClassifier(model).classifier
            new_pred = Predicate(pred.name, pred.types, classifier)
            self._predicates_to_learn = \
                (self._predicates_to_learn - {pred}) | {new_pred}

        # Learn operators via superclass
        self._learn_operators(self._dataset)


    def _get_states_to_ask(self,
                          trajectories: Dataset) -> List[State]:
        """Gets set of states to ask about, according to ask_strategy.
        """
        new_states = []
        for (ss, _) in trajectories:
            new_states.extend(ss)
        scores = [score_goal(self._ground_atom_dataset,
                             utils.abstract(s, self._get_current_predicates()))
                  for s in new_states]
        if CFG.interactive_ask_strategy == "all_seen_states":
            return new_states
        if CFG.interactive_ask_strategy == "threshold":
            assert isinstance(CFG.interactive_ask_strategy_threshold, float)
            return [s for (s, score) in zip(new_states, scores)
                    if score >= CFG.interactive_ask_strategy_threshold]
        if CFG.interactive_ask_strategy == "top_k_percent":
            assert isinstance(CFG.interactive_ask_strategy_pct, float)
            n = int(CFG.interactive_ask_strategy_pct / 100. * len(new_states))
            states_and_scores = list(zip(new_states, scores))
            states_and_scores.sort(key=lambda tup: tup[1], reverse=True)
            return [s for (s, _) in states_and_scores[:n]]
        raise NotImplementedError(f"Ask strategy "
                                  f"{CFG.interactive_ask_strategy} "
                                   "not supported")


    def _ask_teacher(self, state: State, ground_atom: GroundAtom) -> bool:
        """Returns whether the ground atom is true in the state.
        """
        return self._teacher.ask(state, ground_atom)


class _Teacher:
    """Answers queries about GroundAtoms in States.
    """
    def __init__(self, all_predicates: Set[Predicate],
                 predicates_to_learn: Set[Predicate]) -> None:
        self._name_to_predicate = {p.name : p for p in all_predicates}
        self._predicates_to_learn = predicates_to_learn
        self._has_generated_data = False

    def generate_data(self, dataset: Dataset) -> List[List[Set[GroundAtom]]]:
        """Creates sparse dataset of GroundAtoms.
        """
        # No cheating!
        assert not self._has_generated_data
        self._has_generated_data = True
        return create_teacher_dataset(self._predicates_to_learn, dataset)

    def ask(self, state: State, ground_atom: GroundAtom) -> bool:
        """Returns whether the ground atom is true in the state.
        """
        # Find the predicate that has the classifier
        predicate = self._name_to_predicate[ground_atom.predicate.name]
        # Use the predicate's classifier
        return predicate.holds(state, ground_atom.objects)


def create_teacher_dataset(preds: Collection[Predicate],
                           dataset: Dataset) -> List[List[Set[GroundAtom]]]:
    """Create sparse dataset of GroundAtoms for interactive learning.
    """
    ratio = CFG.teacher_dataset_label_ratio
    rng = np.random.default_rng(CFG.seed)
    ground_atoms_dataset = []
    for (ss, _) in dataset:
        ground_atoms_traj = []
        for s in ss:
            ground_atoms = sorted(utils.abstract(s, preds))
            # select random subset to keep
            n_samples = int(len(ground_atoms) * ratio)
            if n_samples < 1:
                raise ApproachFailure("Need at least 1 ground atom sample")
            subset = rng.choice(np.arange(len(ground_atoms)),
                                size=(n_samples,),
                                replace=False)
            subset_atoms = {ground_atoms[j] for j in subset}
            ground_atoms_traj.append(subset_atoms)
        ground_atoms_dataset.append(ground_atoms_traj)
    assert len(ground_atoms_dataset) == len(dataset)
    return ground_atoms_dataset


def glib_sample(initial_state: State,
                predicates: Set[Predicate],
                ground_atom_dataset: List[List[Set[GroundAtom]]]
                ) -> List[Task]:
    """Sample some tasks via the GLIB approach.
    """
    print("Sampling a task using GLIB approach...")
    assert CFG.interactive_atom_type_babbled == "ground"
    rng = np.random.default_rng(CFG.seed)
    ground_atoms = utils.all_possible_ground_atoms(initial_state, predicates)
    goals = []  # list of (goal, score) tuples
    for _ in range(CFG.interactive_num_babbles):
        # Sample num atoms to babble
        num_atoms = 1 + rng.choice(CFG.interactive_max_num_atoms_babbled)
        # Sample goal (a set of atoms)
        idxs = rng.choice(np.arange(len(ground_atoms)),
                          size=(num_atoms,),
                          replace=False)
        goal = {ground_atoms[i] for i in idxs}
        goals.append((goal, score_goal(ground_atom_dataset, goal)))
    goals.sort(key=lambda tup: tup[1], reverse=True)
    return [Task(initial_state, g) for (g, _) in \
            goals[:CFG.interactive_num_tasks_babbled]]


def score_goal(ground_atom_dataset: List[List[Set[GroundAtom]]],
               goal: Set[GroundAtom]) -> float:
    """Score a goal as inversely proportional to the number of examples seen
    during training.
    """
    count = 1  # Avoid division by 0
    for trajectory in ground_atom_dataset:
        for ground_atom_set in trajectory:
            count += 1 if goal.issubset(ground_atom_set) else 0
    return 1.0 / count
