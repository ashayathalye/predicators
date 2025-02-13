"""Tests for main.py.
"""

import os
import shutil
import sys
import pytest
from predicators.src.main import main


def test_main():
    """Tests for main.py.
    """
    sys.argv = ["dummy", "--env", "my_env", "--approach", "my_approach",
                "--seed", "123", "--num_test_tasks", "5"]
    with pytest.raises(NotImplementedError):
        main()  # invalid env
    sys.argv = ["dummy", "--env", "cover", "--approach", "my_approach",
                "--seed", "123", "--num_test_tasks", "5"]
    with pytest.raises(NotImplementedError):
        main()  # invalid approach
    sys.argv = ["dummy", "--env", "cover", "--approach", "random_actions",
                "--seed", "123", "--not-a-real-flag", "0"]
    with pytest.raises(ValueError):
        main()  # invalid flag
    sys.argv = ["dummy", "--env", "cover", "--approach", "random_actions",
                "--seed", "123", "--num_test_tasks", "5"]
    main()
    sys.argv = ["dummy", "--env", "cover", "--approach", "random_options",
                "--seed", "123", "--num_test_tasks", "5"]
    main()
    sys.argv = ["dummy", "--env", "cover", "--approach", "oracle",
                "--seed", "123", "--num_test_tasks", "5"]
    main()
    sys.argv = ["dummy", "--env", "cluttered_table", "--approach",
                "random_actions", "--seed", "123", "--num_test_tasks", "20"]
    main()
    sys.argv = ["dummy", "--env", "blocks", "--approach",
                "random_actions", "--seed", "123", "--num_test_tasks", "5"]
    main()
    sys.argv = ["dummy", "--env", "blocks", "--approach",
                "random_options", "--seed", "123", "--num_test_tasks", "5"]
    main()
    video_dir = os.path.join(os.path.dirname(__file__), "_fake_videos")
    sys.argv = ["dummy", "--env", "cover", "--approach", "trivial_learning",
                "--seed", "123", "--make_videos", "--num_test_tasks", "1",
                "--video_dir", video_dir]
    main()
    shutil.rmtree(video_dir)
    # Try running main with a strong timeout.
    sys.argv = ["dummy", "--env", "cover", "--approach", "oracle",
                "--seed", "123", "--timeout", "0.001", "--num_test_tasks", "5"]
    main()
    # Try loading.
    sys.argv = ["dummy", "--env", "cover", "--approach", "operator_learning",
                "--seed", "2348393", "--load"]
    with pytest.raises(FileNotFoundError):
        main()
    # Try predicate exclusion.
    sys.argv = ["dummy", "--env", "cover", "--approach",
                "random_options", "--seed", "123",
                "--excluded_predicates", "NotARealPredicate"]
    with pytest.raises(AssertionError):
        main()  # can't exclude a non-existent predicate
    sys.argv = ["dummy", "--env", "cover", "--approach",
                "random_options", "--seed", "123",
                "--excluded_predicates", "Covers"]
    with pytest.raises(AssertionError):
        main()  # can't exclude a goal predicate
    sys.argv = ["dummy", "--env", "cover", "--approach",
                "random_options", "--seed", "123",
                "--excluded_predicates", "Holding,HandEmpty"]
    main()  # correct usage
    sys.argv = ["dummy", "--env", "cover", "--approach",
                "random_options", "--seed", "123",
                "--excluded_predicates", "HandEmpty",
                "--num_test_tasks", "5"]
    main()  # correct usage
