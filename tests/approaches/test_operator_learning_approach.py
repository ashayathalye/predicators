"""Test cases for the operator learning approach.
"""

from predicators.src.envs import create_env
from predicators.src.approaches import create_approach
from predicators.src.datasets import create_dataset
from predicators.src.settings import CFG
from predicators.src import utils


def _test_approach(env_name, approach_name, excluded_predicates="",
                   try_solving=True):
    """Integration test for the given approach.
    """
    utils.update_config({"env": env_name, "approach": approach_name,
                         "timeout": 10, "max_samples_per_step": 10,
                         "seed": 12345, "regressor_max_itr": 200,
                         "classifier_max_itr_sampler": 200,
                         "classifier_max_itr_predicate": 200,
                         "excluded_predicates": excluded_predicates})
    env = create_env(env_name)
    assert env.goal_predicates.issubset(env.predicates)
    if CFG.excluded_predicates:
        excludeds = set(CFG.excluded_predicates.split(","))
        assert excludeds.issubset({pred.name for pred in env.predicates}), \
            "Unrecognized excluded_predicates!"
        preds = {pred for pred in env.predicates
                 if pred.name not in excludeds}
        assert env.goal_predicates.issubset(preds), \
            "Can't exclude a goal predicate!"
    else:
        preds = env.predicates
    approach = create_approach(approach_name,
        env.simulate, preds, env.options, env.types,
        env.action_space, env.get_train_tasks())
    dataset = create_dataset(env)
    assert approach.is_learning_based
    approach.learn_from_offline_dataset(dataset)
    task = env.get_test_tasks()[0]
    if try_solving:
        approach.solve(task, timeout=CFG.timeout)
    # We won't check the policy here because we don't want unit tests to
    # have to train very good models, since that would be slow.
    # Now test loading operators & predicates.
    approach2 = create_approach(approach_name,
        env.simulate, preds, env.options, env.types,
        env.action_space, env.get_train_tasks())
    approach2.load()
    if try_solving:
        approach2.solve(task, timeout=CFG.timeout)


def test_operator_learning_approach():
    """Tests for OperatorLearningApproach class.
    """
    _test_approach(env_name="cover", approach_name="operator_learning")


def test_iterative_invention_approach():
    """Tests for IterativeInventionApproach class.
    """
    _test_approach(env_name="blocks", approach_name="iterative_invention",
                   excluded_predicates="Holding")
    _test_approach(env_name="cover", approach_name="iterative_invention",
                   excluded_predicates="Holding", try_solving=False)
