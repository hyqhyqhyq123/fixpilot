# 测试用，可以在 Python 交互环境或脚本中运行
from app.tools.repo_clone_tool import clone_repo, validate_repo_url
from app.tools.repo_analysis_tool import list_files, get_file_tree_text

# 1. 测试 URL 验证
print(validate_repo_url("https://github.com/pallets/flask"))      # True
print(validate_repo_url("git@github.com:pallets/flask.git"))       # False
print(validate_repo_url("https://evil.com/malware"))               # False

# 2. 测试 clone（会真的下载代码，需要网络）
result = clone_repo(task_id=999, repo_url="https://github.com/pallets/click")
print(result)

# 3. 如果 clone 成功，测试文件分析
if result["success"]:
    analysis = list_files(result["repo_path"])
    print(get_file_tree_text(analysis))