# Naming Contract

- codebase_play_t:
  第 t 轮参赛前的完整代码库快照。

- submission_t:
  从 codebase_play_t 导出的真正参赛产物。

- codebase_post_t:
  第 t 轮 revision 完成后的完整代码库快照。

- codebase_final:
  整个 tournament 最后一轮 revision 后的终态代码库。

- logs/round_t/:
  第 t 轮的 replay、stderr、build/test log、scorecard、diff 等回写目录。

- workspace/codebases/<tournament>/<side>/codebase_play_t:
  第 t 轮实际使用的完整代码库目录。

- workspace/submissions/<tournament>/<side>/submission_t:
  从 codebase_play_t 导出的实际 submission 目录。
