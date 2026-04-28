import pommerman
from pommerman import agents

# 如果你刚才在 simple_ffa_run.py 里看到的环境名不是这个，
# 就把下面这一行改成示例文件里的原始环境名。
ENV_ID = "PommeFFACompetition-v0"

agent_list = [
    agents.SimpleAgent(),
    agents.SimpleAgent(),
    agents.SimpleAgent(),
    agents.SimpleAgent(),
]

env = pommerman.make(ENV_ID, agent_list)

try:
    state = env.reset()
    done = False
    step_count = 0

    while not done and step_count < 800:
        actions = env.act(state)
        state, reward, done, info = env.step(actions)
        step_count += 1

    print("done:", done)
    print("steps:", step_count)
    print("reward:", reward)
    print("info:", info)
finally:
    env.close()
