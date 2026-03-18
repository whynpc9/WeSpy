# AGENTS

## Test Output Directory

- 仓库内所有人工测试、回归验证、示例抓取产物，统一写入 `.tmp/test-output/`
- 不要在仓库根目录新增新的测试输出目录，例如 `test_output/`、`test_output_clean_*`、`debug_output/`
- 程序默认业务输出目录 `articles/` 不变；只有仓库内的测试产物需要遵守这个规则
- 提交前保持 `.tmp/test-output/` 下内容可忽略，不把测试产物加入版本控制
