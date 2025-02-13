"""Test cases for the blocks environment.
"""

import numpy as np
from predicators.src.envs import BlocksEnv
from predicators.src import utils
from predicators.src.settings import CFG


def test_blocks():
    """Tests for BlocksEnv class.
    """
    utils.update_config({"env": "blocks"})
    env = BlocksEnv()
    env.seed(123)
    for task in env.get_train_tasks():
        for obj in task.init:
            assert len(obj.type.feature_names) == len(task.init[obj])
    for task in env.get_test_tasks():
        for obj in task.init:
            assert len(obj.type.feature_names) == len(task.init[obj])
    assert len(env.predicates) == 5
    assert {pred.name for pred in env.goal_predicates} == {"On", "OnTable"}
    assert len(env.options) == 3
    assert len(env.types) == 2
    block_type = [t for t in env.types if t.name == "block"][0]
    assert env.action_space.shape == (4,)
    assert abs(env.action_space.low[0]-BlocksEnv.x_lb) < 1e-3
    assert abs(env.action_space.high[0]-BlocksEnv.x_ub) < 1e-3
    assert abs(env.action_space.low[1]-BlocksEnv.y_lb) < 1e-3
    assert abs(env.action_space.high[1]-BlocksEnv.y_ub) < 1e-3
    assert abs(env.action_space.low[2]) < 1e-3
    assert abs(env.action_space.low[3]) < 1e-3
    assert abs(env.action_space.high[3]-1) < 1e-3
    for i, task in enumerate(env.get_test_tasks()):
        state = task.init
        robot = None
        for item in state:
            if item.type != block_type:
                robot = item
                continue
            assert not (state.get(item, "held") and state.get(item, "clear"))
        assert robot is not None
        if i == 0:
            # Force initial pick to test rendering with holding
            Pick = [o for o in env.options if o.name == "Pick"][0]
            block = sorted([o for o in state if o.type.name == "block" and \
                            state.get(o, 'clear') > env.clear_tol])[0]
            act = Pick.ground([robot, block], np.zeros(3)).policy(state)
            state = env.simulate(state, act)
            env.render(state, task)

def test_blocks_failure_cases():
    """Tests for the cases where simulate() is a no-op.
    """
    utils.update_config({"env": "blocks"})
    env = BlocksEnv()
    env.seed(123)
    Pick = [o for o in env.options if o.name == "Pick"][0]
    Stack = [o for o in env.options if o.name == "Stack"][0]
    PutOnTable = [o for o in env.options if o.name == "PutOnTable"][0]
    On = [o for o in env.predicates if o.name == "On"][0]
    OnTable = [o for o in env.predicates if o.name == "OnTable"][0]
    block_type = [t for t in env.types if t.name == "block"][0]
    robot_type = [t for t in env.types if t.name == "robot"][0]
    block0 = block_type("block0")
    block1 = block_type("block1")
    block2 = block_type("block2")
    robot = robot_type("robot")
    task = env.get_train_tasks()[0]
    state = task.init
    atoms = utils.abstract(state, env.predicates)
    assert OnTable([block0]) in atoms
    assert OnTable([block1]) in atoms
    assert OnTable([block2]) not in atoms
    assert On([block2, block1]) in atoms
    # No block at this pose, pick fails
    act = Pick.ground([robot, block0], np.array(
        [0, -1, 0], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Object not clear, pick fails
    act = Pick.ground([robot, block1], np.array(
        [0, 0, 0], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Cannot putontable or stack without picking first
    act = Stack.ground([robot, block1], np.array(
        [0, 0, 0], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    act = PutOnTable.ground([robot], np.array(
        [0.5, 0.5], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Perform valid pick
    act = Pick.ground([robot, block0], np.array(
        [0, 0, 0], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.any(state[o] != next_state[o] for o in state)
    # Change the state
    state = next_state
    # Cannot pick twice in a row
    act = Pick.ground([robot, block2], np.array(
        [0, 0, 0], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Cannot stack onto non-clear block
    act = Stack.ground([robot, block1], np.array(
        [0, 0, CFG.blocks_block_size], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Cannot stack onto no block
    act = Stack.ground([robot, block1], np.array(
        [0, -1, CFG.blocks_block_size], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
    # Cannot stack onto yourself
    act = Stack.ground([robot, block0], np.array(
        [0, 0, CFG.blocks_block_size], dtype=np.float32)).policy(state)
    next_state = env.simulate(state, act)
    assert np.all(state[o] == next_state[o] for o in state)
