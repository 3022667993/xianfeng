from starter_repos.pommerman_1v1.scripts.seed_control import apply_env_seed, apply_pre_env_seed, apply_seed_to_env


class EnvSeedOnly:
    def __init__(self):
        self.seed_called = None
        self.seed_return = [None]
        self.reset_calls = 0

    def reset(self, *args, **kwargs):
        self.reset_calls += 1
        if "seed" in kwargs:
            raise TypeError("reset() got an unexpected keyword argument 'seed'")
        return None

    def seed(self, seed):
        self.seed_called = seed
        self.seed_return = [seed]
        return self.seed_return


class EnvReject:
    def reset(self, seed=None):
        raise RuntimeError("seed unsupported")


class EnvNoSeedNoReset:
    pass


def test_apply_pre_env_seed_does_not_claim_applied():
    out = apply_pre_env_seed(123)
    assert out["requested_seed"] == 123
    assert out["applied_seed"] is None
    assert out["seed"] is None
    assert out["seed_control_status"] == "requested_but_not_applied"
    assert out["seed_control_method_applied"] is None
    assert isinstance(out["seed_control_methods_attempted"], list) and out["seed_control_methods_attempted"]
    assert "random.seed(...)" in out["seed_control_methods_attempted"]


def test_apply_env_seed_with_env_seed_support():
    env = EnvSeedOnly()
    out = apply_env_seed(env, 123, prior_provenance=apply_pre_env_seed(123))
    assert out["applied_seed"] == 123
    assert out["seed"] == 123
    assert out["seed_control_status"] == "applied"
    assert out["seed_control_error"] is None
    assert out["seed_control_method_applied"] == "env.seed(...)"
    assert isinstance(out["seed_control_methods_attempted"], list) and out["seed_control_methods_attempted"]
    assert "env.seed(...)" in out["seed_control_methods_attempted"]
    assert out["seed_control_env_seed_return"] == [123]
    assert env.seed_called == 123


def test_apply_seed_to_env_with_env_seed_support():
    env = EnvSeedOnly()
    out = apply_seed_to_env(env, 456)
    assert out["applied_seed"] == 456
    assert out["seed"] == 456
    assert out["seed_control_status"] == "applied"
    assert out["seed_control_error"] is None
    assert out["seed_control_method_applied"] == "env.seed(...)"
    assert isinstance(out["seed_control_methods_attempted"], list) and out["seed_control_methods_attempted"]
    assert "env.seed(...)" in out["seed_control_methods_attempted"]
    assert out["seed_control_env_seed_return"] == [456]
    assert env.seed_called == 456


def test_apply_seed_rejected():
    env = EnvReject()
    out = apply_env_seed(env, 789, prior_provenance=apply_pre_env_seed(789))
    assert out["applied_seed"] is None
    assert out["seed"] is None
    assert out["seed_control_status"] in {"requested_but_not_applied", "unsupported_by_environment"}
    assert isinstance(out["seed_control_error"], str) and out["seed_control_error"].strip()
    assert isinstance(out["seed_control_methods_attempted"], list) and out["seed_control_methods_attempted"]
    assert "env.seed(...)" in out["seed_control_methods_attempted"]
    assert out["seed_control_env_seed_return"] is None


def test_apply_seed_not_requested():
    env = EnvNoSeedNoReset()
    out = apply_seed_to_env(env, None)
    assert out["requested_seed"] is None
    assert out["applied_seed"] is None
    assert out["seed"] is None
    assert out["seed_control_status"] == "not_requested"
    assert out["seed_control_error"] is None
    assert out["seed_control_methods_attempted"] == []
    assert out["seed_control_method_applied"] is None
    assert out["seed_control_env_seed_return"] is None
