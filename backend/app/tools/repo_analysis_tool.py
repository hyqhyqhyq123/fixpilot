# backend/app/tools/repo_analysis_tool.py
# 作用：分析 clone 下来的仓库，列出文件结构并识别项目详细信息
#
# 为什么需要这个工具？
# Agent 需要了解仓库的"全貌"才能找到该改哪些文件。
# 不能把整个 repo 一股脑塞给 LLM（太大，会超 token 限制），
# 所以先做一个"目录扫描 + 项目诊断"，让 Agent 知道：
# - 这是什么语言/框架写的？
# - 用什么包管理器？
# - 怎么跑测试？怎么跑 lint？
# - 有哪些重要的源码文件？

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── 需要过滤的目录 ───────────────────────────────────────────
# 这些目录对 Agent 分析代码没有帮助，反而会产生大量噪音

IGNORED_DIRS: set[str] = {
    ".git", ".svn", ".hg",
    "node_modules", "vendor", ".venv", "venv", "env",
    "__pycache__", ".tox", ".nox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache",
    "dist", "build", "out", "target", ".next", ".nuxt",
    ".idea", ".vscode", ".cursor",
    ".eggs", "htmlcov",
}

IGNORED_FILES: set[str] = {
    ".DS_Store", "Thumbs.db", ".gitattributes",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "Gemfile.lock",
    "composer.lock",
}

# 关键目录名称（会在文件树中特别标注）
KEY_DIRS: set[str] = {
    "src", "lib", "app", "core",          # 源码目录
    "tests", "test", "__tests__", "spec", # 测试目录
    "docs", "doc", "documentation",       # 文档目录
    "config", "configs", "conf",          # 配置目录
    "scripts", "bin",                     # 脚本目录
    "api", "routes", "handlers",          # API 层
    "models", "schemas", "db",            # 数据层
    "utils", "helpers", "common",         # 工具层
}

# 关键文件名称（会在文件树中特别标注）
KEY_FILES: set[str] = {
    "package.json", "pyproject.toml", "requirements.txt",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".env.example", "README.md", "CHANGELOG.md",
    "setup.py", "setup.cfg", "Pipfile",
}

# 大型 repo 的文件数阈值，超过此数量时限制树的深度为 3
LARGE_REPO_THRESHOLD = 500
MAX_FILES = 5000
MAX_FILES_PER_DIR = 100


# ── 项目特征文件规则 ─────────────────────────────────────────
# 每条规则：文件名 → (项目类型, 主语言, 包管理器)

PROJECT_MARKERS: dict[str, tuple[str, str, str]] = {
    "package.json":    ("nodejs",       "JavaScript/TypeScript", "npm"),
    "pyproject.toml":  ("python",       "Python",               "poetry/pip"),
    "requirements.txt":("python",       "Python",               "pip"),
    "setup.py":        ("python",       "Python",               "pip"),
    "Pipfile":         ("python",       "Python",               "pipenv"),
    "go.mod":          ("go",           "Go",                   "go modules"),
    "pom.xml":         ("java-maven",   "Java",                 "maven"),
    "build.gradle":    ("java-gradle",  "Java",                 "gradle"),
    "build.gradle.kts":("java-gradle",  "Kotlin",               "gradle"),
    "Cargo.toml":      ("rust",         "Rust",                 "cargo"),
    "Gemfile":         ("ruby",         "Ruby",                 "bundler"),
    "composer.json":   ("php",          "PHP",                  "composer"),
    "CMakeLists.txt":  ("cmake",        "C/C++",                "cmake"),
}

# ── 框架检测规则 ─────────────────────────────────────────────
# 格式：(检测方式, 检测值, 框架名称)
# 检测方式：
#   "file"  → 根目录存在此文件
#   "dir"   → 根目录存在此目录
#   "dep"   → package.json 或 pyproject.toml 中包含此依赖名

FRAMEWORK_RULES: list[tuple[str, str, str]] = [
    # Python 框架
    ("file", "manage.py",         "Django"),
    ("dep",  "django",            "Django"),
    ("dep",  "fastapi",           "FastAPI"),
    ("dep",  "flask",             "Flask"),
    ("dep",  "starlette",         "Starlette"),
    ("dep",  "tornado",           "Tornado"),
    ("dep",  "aiohttp",           "aiohttp"),
    # Node.js 框架
    ("dep",  "next",              "Next.js"),
    ("dep",  "react",             "React"),
    ("dep",  "vue",               "Vue"),
    ("dep",  "express",           "Express"),
    ("dep",  "nestjs/core",       "NestJS"),
    ("dep",  "fastify",           "Fastify"),
    ("dep",  "nuxt",              "Nuxt.js"),
    ("dep",  "svelte",            "Svelte"),
    # Go 框架
    ("dep",  "gin-gonic/gin",     "Gin"),
    ("dep",  "labstack/echo",     "Echo"),
    ("dep",  "gofiber/fiber",     "Fiber"),
    # Java 框架
    ("dep",  "spring-boot",       "Spring Boot"),
    ("dep",  "spring-framework",  "Spring"),
    # Rust 框架
    ("dep",  "actix-web",         "Actix Web"),
    ("dep",  "axum",              "Axum"),
    ("dep",  "rocket",            "Rocket"),
]

# ── 测试框架检测规则 ─────────────────────────────────────────
# 格式：(检测方式, 检测值, 框架名, 默认测试命令)

TEST_FRAMEWORK_RULES: list[tuple[str, str, str, str]] = [
    ("dep",  "pytest",            "pytest",    "pytest"),
    ("dep",  "unittest",          "unittest",  "python -m unittest"),
    ("dep",  "jest",              "Jest",      "npm test"),
    ("dep",  "vitest",            "Vitest",    "npm test"),
    ("dep",  "mocha",             "Mocha",     "npm test"),
    ("dep",  "jasmine",           "Jasmine",   "npm test"),
    ("dep",  "testing-library",   "Testing Library", "npm test"),
    ("file", "pytest.ini",        "pytest",    "pytest"),
    ("file", "jest.config.js",    "Jest",      "npm test"),
    ("file", "jest.config.ts",    "Jest",      "npm test"),
    ("file", "vitest.config.ts",  "Vitest",    "npx vitest"),
    # Go/Rust/Java 的测试命令不需要额外框架检测
]

# ── lint 工具检测规则 ─────────────────────────────────────────
# 格式：(检测方式, 检测值, 工具名, 默认 lint 命令)

LINT_RULES: list[tuple[str, str, str, str]] = [
    ("file", ".ruff.toml",        "ruff",      "ruff check ."),
    ("dep",  "ruff",              "ruff",      "ruff check ."),
    ("dep",  "flake8",            "flake8",    "flake8 ."),
    ("dep",  "pylint",            "pylint",    "pylint src"),
    ("dep",  "eslint",            "ESLint",    "npx eslint ."),
    ("file", ".eslintrc.js",      "ESLint",    "npx eslint ."),
    ("file", ".eslintrc.json",    "ESLint",    "npx eslint ."),
    ("file", ".eslintrc.yml",     "ESLint",    "npx eslint ."),
    ("dep",  "prettier",          "Prettier",  "npx prettier --check ."),
]

# ── type check 工具检测规则 ──────────────────────────────────
# 格式：(检测方式, 检测值, 工具名, 默认命令)

TYPECHECK_RULES: list[tuple[str, str, str, str]] = [
    ("dep",  "mypy",              "mypy",      "mypy ."),
    ("dep",  "pyright",           "pyright",   "pyright"),
    ("dep",  "typescript",        "tsc",       "npx tsc --noEmit"),
    ("file", "tsconfig.json",     "tsc",       "npx tsc --noEmit"),
    ("dep",  "pytype",            "pytype",    "pytype ."),
]

# ── 入口文件检测 ─────────────────────────────────────────────
# 按优先级顺序检测，找到第一个即停止

ENTRY_FILE_CANDIDATES: list[str] = [
    "main.py", "app.py", "server.py", "run.py",
    "index.ts", "index.js", "main.ts", "main.js",
    "src/main.py", "src/app.py",
    "src/index.ts", "src/index.js",
    "src/main.ts", "src/main.js",
    "app/main.py",
    "cmd/main.go", "main.go",
    "src/main.rs",
]


# ── Pydantic 输出结构 ────────────────────────────────────────

class ProjectTypeInfo(BaseModel):
    """项目类型基础信息。"""
    project_type: str = Field(description="项目类型，如 python、nodejs、go")
    language: str = Field(description="主要编程语言")
    package_manager: str = Field(description="包管理器，如 pip、npm、cargo")
    marker_file: str = Field(description="用于识别的特征文件")


class ProjectInfo(BaseModel):
    """
    完整的项目分析结果，对应需求文档 FR-102。

    这个对象会被存入 LangGraph State 的 project_info 字段，
    后续 Tester Agent 和 Planner Agent 都会用到这些信息。
    """
    # 基础信息
    project_types: list[ProjectTypeInfo] = Field(description="识别到的项目类型（可能多个）")
    primary_language: Optional[str] = Field(default=None, description="主要编程语言")
    primary_type: Optional[str] = Field(default=None, description="主要项目类型")
    package_manager: Optional[str] = Field(default=None, description="包管理器")

    # 框架
    frameworks: list[str] = Field(default_factory=list, description="检测到的框架，如 FastAPI、React")

    # 测试相关
    test_framework: Optional[str] = Field(default=None, description="测试框架，如 pytest、Jest")
    test_command: Optional[str] = Field(default=None, description="推荐的测试命令，如 pytest")
    test_directories: list[str] = Field(
        default_factory=list,
        description="检测到的测试目录，如 tests、__tests__",
    )

    # lint 相关
    lint_tool: Optional[str] = Field(default=None, description="lint 工具，如 ruff、ESLint")
    lint_command: Optional[str] = Field(default=None, description="推荐的 lint 命令")

    # type check 相关
    typecheck_tool: Optional[str] = Field(default=None, description="类型检查工具，如 mypy、tsc")
    typecheck_command: Optional[str] = Field(default=None, description="推荐的 type check 命令")

    # 入口文件
    entry_file: Optional[str] = Field(default=None, description="项目入口文件，如 main.py")

    # 关键配置文件
    key_config_files: list[str] = Field(
        default_factory=list,
        description="关键配置文件列表，如 pyproject.toml、Dockerfile"
    )


class RepoAnalysisResult(BaseModel):
    """
    仓库分析的完整结果，包含文件树 + 项目信息。
    """
    repo_path: str = Field(description="仓库在 workspace 中的路径")
    total_files: int = Field(description="文件总数（过滤后）")
    total_dirs: int = Field(description="目录总数（过滤后）")
    file_tree: list[str] = Field(description="文件树结构（文本格式，带标注）")
    project_info: ProjectInfo = Field(description="完整的项目分析结果")
    truncated: bool = Field(default=False, description="文件树是否被截断")
    depth_limited: bool = Field(default=False, description="是否因为文件量大而限制了深度")


# ── 依赖读取辅助函数 ─────────────────────────────────────────

def _read_package_json_deps(repo_path: Path) -> set[str]:
    """
    读取 package.json 中的依赖名称（全部转小写）。

    为什么需要这个？
    前端/Node.js 项目的框架通过依赖名称判断，比如
    "dependencies": { "react": "^18.0.0" } → 说明是 React 项目。
    """
    pkg_file = repo_path / "package.json"
    if not pkg_file.exists():
        return set()
    try:
        import json
        data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))
        deps: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            deps.update(k.lower() for k in data.get(section, {}).keys())
        return deps
    except Exception as e:
        logger.warning(f"读取 package.json 失败：{e}")
        return set()


def _read_python_deps(repo_path: Path) -> set[str]:
    """
    读取 Python 项目的依赖名称（全部转小写）。

    依次尝试读取 pyproject.toml、requirements.txt、setup.py。
    """
    deps: set[str] = set()

    # 尝试 pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="ignore").lower()
            # 简单的文本扫描，不引入 tomllib 解析复杂度
            # 找所有 "package-name" 格式的字符串
            import re
            found = re.findall(r'"([\w\-]+)\s*[>=<!\[]', content)
            deps.update(found)
        except Exception as e:
            logger.warning(f"读取 pyproject.toml 失败：{e}")

    # 尝试 requirements.txt
    req_file = repo_path / "requirements.txt"
    if req_file.exists():
        try:
            import re
            for line in req_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip().lower()
                if line and not line.startswith("#"):
                    # requirements.txt 格式：package>=1.0 或 package==1.0 或 package
                    match = re.match(r"^([\w\-]+)", line)
                    if match:
                        deps.add(match.group(1))
        except Exception as e:
            logger.warning(f"读取 requirements.txt 失败：{e}")

    return deps


def _read_go_deps(repo_path: Path) -> set[str]:
    """读取 go.mod 中的依赖路径。"""
    go_mod = repo_path / "go.mod"
    if not go_mod.exists():
        return set()
    try:
        import re
        content = go_mod.read_text(encoding="utf-8", errors="ignore").lower()
        return set(re.findall(r'"([\w\.\-/]+)"', content))
    except Exception:
        return set()


def _read_cargo_deps(repo_path: Path) -> set[str]:
    """读取 Cargo.toml 中的依赖名。"""
    cargo = repo_path / "Cargo.toml"
    if not cargo.exists():
        return set()
    try:
        import re
        content = cargo.read_text(encoding="utf-8", errors="ignore").lower()
        return set(re.findall(r'^([\w\-]+)\s*=', content, re.MULTILINE))
    except Exception:
        return set()


def _check_rule(
    method: str,
    value: str,
    repo_path: Path,
    all_deps: set[str],
) -> bool:
    """
    检查单条规则是否匹配。

    method:
        "file" → 检查根目录是否存在此文件
        "dir"  → 检查根目录是否存在此目录
        "dep"  → 检查依赖集合中是否包含此包名（部分匹配）
    """
    if method == "file":
        return (repo_path / value).exists()
    elif method == "dir":
        return (repo_path / value).is_dir()
    elif method == "dep":
        # 部分匹配：比如 "react" 能匹配 "@types/react"、"react-dom"
        return any(value.lower() in dep for dep in all_deps)
    return False


def _find_test_directories(root: Path) -> list[str]:
    """查找常见测试目录，给 Planner 判断是否应该补测试。"""

    test_dir_names = {"tests", "test", "__tests__", "spec"}
    found: list[str] = []

    for path in root.rglob("*"):
        if len(found) >= 20:
            break
        if not path.is_dir() or path.name not in test_dir_names:
            continue

        relative_path = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        found.append(relative_path.as_posix())

    return found


# ── 核心分析函数 ─────────────────────────────────────────────

def detect_project_info(repo_path: str) -> ProjectInfo:
    """
    深度分析项目，识别语言、框架、包管理器、测试框架、lint 工具等。

    这是需求文档 FR-102 的完整实现。

    参数:
        repo_path: 仓库根目录路径

    返回:
        ProjectInfo: 包含完整项目分析信息
    """
    root = Path(repo_path)

    # 第 1 步：识别项目类型（语言 + 包管理器）
    project_types: list[ProjectTypeInfo] = []
    seen_types: set[str] = set()
    for marker_file, (proj_type, language, pkg_mgr) in PROJECT_MARKERS.items():
        if (root / marker_file).exists() and proj_type not in seen_types:
            project_types.append(ProjectTypeInfo(
                project_type=proj_type,
                language=language,
                package_manager=pkg_mgr,
                marker_file=marker_file,
            ))
            seen_types.add(proj_type)

    primary_type = project_types[0].project_type if project_types else None
    primary_language = project_types[0].language if project_types else None
    package_manager = project_types[0].package_manager if project_types else None

    # 第 2 步：读取依赖列表（用于后续框架/测试/lint 检测）
    all_deps: set[str] = set()
    if primary_type == "nodejs":
        all_deps = _read_package_json_deps(root)
    elif primary_type == "python":
        all_deps = _read_python_deps(root)
    elif primary_type == "go":
        all_deps = _read_go_deps(root)
    elif primary_type == "rust":
        all_deps = _read_cargo_deps(root)

    # 第 3 步：检测框架
    frameworks: list[str] = []
    seen_frameworks: set[str] = set()
    for method, value, framework_name in FRAMEWORK_RULES:
        if framework_name not in seen_frameworks:
            if _check_rule(method, value, root, all_deps):
                frameworks.append(framework_name)
                seen_frameworks.add(framework_name)

    # 第 4 步：检测测试框架
    test_framework: Optional[str] = None
    test_command: Optional[str] = None
    # Go/Rust/Java 不需要检测依赖，直接给默认命令
    default_test_cmds = {
        "go": "go test ./...",
        "rust": "cargo test",
        "java-maven": "mvn test",
        "java-gradle": "gradle test",
        "ruby": "bundle exec rspec",
    }
    if primary_type in default_test_cmds:
        test_command = default_test_cmds[primary_type]
    else:
        for method, value, fw_name, cmd in TEST_FRAMEWORK_RULES:
            if _check_rule(method, value, root, all_deps):
                test_framework = fw_name
                test_command = cmd
                break

    # 第 5 步：检测 lint 工具
    lint_tool: Optional[str] = None
    lint_command: Optional[str] = None
    # Go/Rust 有内置 lint
    default_lint_cmds = {
        "go": "go vet ./...",
        "rust": "cargo clippy",
    }
    if primary_type in default_lint_cmds:
        lint_command = default_lint_cmds[primary_type]
    else:
        for method, value, tool_name, cmd in LINT_RULES:
            if _check_rule(method, value, root, all_deps):
                lint_tool = tool_name
                lint_command = cmd
                break

    # 第 6 步：检测 type check 工具
    typecheck_tool: Optional[str] = None
    typecheck_command: Optional[str] = None
    for method, value, tool_name, cmd in TYPECHECK_RULES:
        if _check_rule(method, value, root, all_deps):
            typecheck_tool = tool_name
            typecheck_command = cmd
            break

    # 第 7 步：检测入口文件
    entry_file: Optional[str] = None
    for candidate in ENTRY_FILE_CANDIDATES:
        if (root / candidate).exists():
            entry_file = candidate
            break

    # 第 8 步：查找测试目录。FR-503 要求 bug fix 优先补测试，
    # 所以这里把“项目有没有测试目录”做成结构化信号传给 Planner。
    test_directories = _find_test_directories(root)

    # 第 9 步：收集关键配置文件
    key_config_files = [
        f for f in KEY_FILES
        if (root / f).exists()
    ]

    logger.info(
        f"项目分析完成：language={primary_language}, "
        f"frameworks={frameworks}, test={test_command}, lint={lint_command}"
    )

    return ProjectInfo(
        project_types=project_types,
        primary_language=primary_language,
        primary_type=primary_type,
        package_manager=package_manager,
        frameworks=frameworks,
        test_framework=test_framework,
        test_command=test_command,
        test_directories=test_directories,
        lint_tool=lint_tool,
        lint_command=lint_command,
        typecheck_tool=typecheck_tool,
        typecheck_command=typecheck_command,
        entry_file=entry_file,
        key_config_files=key_config_files,
    )


def _should_ignore_dir(name: str) -> bool:
    return name in IGNORED_DIRS


def _should_ignore_file(name: str) -> bool:
    if name in IGNORED_FILES:
        return True
    # 忽略隐藏文件，但保留部分有意义的隐藏文件
    if name.startswith(".") and name not in KEY_FILES and name not in {
        ".env.example", ".gitignore", ".dockerignore",
        ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
        ".prettierrc", ".editorconfig", ".flake8",
        ".ruff.toml",
    }:
        return True
    return False


def list_files(repo_path: str, max_depth: Optional[int] = None) -> RepoAnalysisResult:
    """
    扫描仓库目录，返回带标注的文件树和完整项目分析结果。

    对应需求文档 FR-102 + FR-103。

    参数:
        repo_path: 仓库的绝对路径
        max_depth: 最大扫描深度，None 表示自动决定

    返回:
        RepoAnalysisResult: 文件树 + 项目信息
    """
    root = Path(repo_path)

    if not root.exists():
        raise FileNotFoundError(f"仓库路径不存在：{repo_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"路径不是目录：{repo_path}")

    # ── 第一遍扫描：快速统计文件数量，决定是否限制深度 ──
    quick_count = sum(1 for _ in root.rglob("*") if _.is_file())
    depth_limited = False

    if max_depth is None:
        if quick_count > LARGE_REPO_THRESHOLD:
            # 文件太多时限制只展示 3 层，防止文件树过于庞大
            max_depth = 3
            depth_limited = True
            logger.info(
                f"仓库文件数量 {quick_count} 超过阈值 {LARGE_REPO_THRESHOLD}，"
                f"将文件树深度限制为 {max_depth} 层"
            )

    # ── 第二遍扫描：生成带标注的文件树 ──
    file_tree: list[str] = []
    total_files = 0
    total_dirs = 0
    truncated = False

    def _scan_dir(current_dir: Path, prefix: str, depth: int) -> None:
        nonlocal total_files, total_dirs, truncated

        if total_files >= MAX_FILES:
            truncated = True
            return

        # 如果设置了深度限制，超过后只显示"..."提示
        if max_depth is not None and depth > max_depth:
            return

        try:
            entries = sorted(
                current_dir.iterdir(),
                # 排序规则：目录在前，文件在后，各自按名称排序（不区分大小写）
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except PermissionError:
            logger.warning(f"无权访问目录：{current_dir}")
            return

        dirs = [e for e in entries if e.is_dir() and not _should_ignore_dir(e.name)]
        files = [e for e in entries if e.is_file() and not _should_ignore_file(e.name)]
        all_entries = dirs + files
        file_count_in_dir = 0

        for i, entry in enumerate(all_entries):
            if total_files >= MAX_FILES:
                truncated = True
                return

            is_last = (i == len(all_entries) - 1)
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                total_dirs += 1
                # 关键目录加标注
                label = " [src]" if entry.name in KEY_DIRS else ""
                # 深度达到上限时，显示"..."提示还有内容
                if max_depth is not None and depth == max_depth:
                    file_tree.append(f"{prefix}{connector}{entry.name}/{label} ...")
                else:
                    file_tree.append(f"{prefix}{connector}{entry.name}/{label}")
                    _scan_dir(entry, prefix + extension, depth + 1)
            else:
                total_files += 1
                file_count_in_dir += 1

                if file_count_in_dir <= MAX_FILES_PER_DIR:
                    # 关键文件加标注
                    label = " [key]" if entry.name in KEY_FILES else ""
                    file_tree.append(f"{prefix}{connector}{entry.name}{label}")
                elif file_count_in_dir == MAX_FILES_PER_DIR + 1:
                    remaining = len(files) - MAX_FILES_PER_DIR
                    file_tree.append(f"{prefix}{connector}... ({remaining} more files)")

    _scan_dir(root, "", 0)

    # ── 深度分析项目 ──
    project_info = detect_project_info(repo_path)

    return RepoAnalysisResult(
        repo_path=str(root),
        total_files=total_files,
        total_dirs=total_dirs,
        file_tree=file_tree,
        project_info=project_info,
        truncated=truncated,
        depth_limited=depth_limited,
    )


def get_file_tree_text(result: RepoAnalysisResult) -> str:
    """
    将分析结果格式化为可读文本，方便传给 LLM 或打印到终端。

    参数:
        result: list_files() 的返回值

    返回:
        格式化的文本字符串
    """
    info = result.project_info
    lines: list[str] = []

    lines.append("=== 项目信息 ===")

    if info.project_types:
        for pt in info.project_types:
            lines.append(
                f"  语言：{pt.language}  |  "
                f"类型：{pt.project_type}  |  "
                f"包管理器：{pt.package_manager}  |  "
                f"检测文件：{pt.marker_file}"
            )
    else:
        lines.append("  语言：未识别")

    if info.frameworks:
        lines.append(f"  框架：{', '.join(info.frameworks)}")

    if info.test_framework or info.test_command:
        fw = f"({info.test_framework})" if info.test_framework else ""
        lines.append(f"  测试框架：{fw}  |  测试命令：{info.test_command or '未检测到'}")

    if info.test_directories:
        lines.append(f"  测试目录：{', '.join(info.test_directories)}")

    if info.lint_tool or info.lint_command:
        lines.append(f"  lint 工具：{info.lint_tool or ''}  |  命令：{info.lint_command or '未检测到'}")

    if info.typecheck_tool or info.typecheck_command:
        lines.append(f"  类型检查：{info.typecheck_tool or ''}  |  命令：{info.typecheck_command or '未检测到'}")

    if info.entry_file:
        lines.append(f"  入口文件：{info.entry_file}")

    if info.key_config_files:
        lines.append(f"  关键配置：{', '.join(info.key_config_files)}")

    lines.append("")
    lines.append(
        f"=== 文件统计：{result.total_files} 个文件，{result.total_dirs} 个目录 ==="
    )

    if result.depth_limited:
        lines.append("  注意：文件较多，文件树已限制为 3 层深度（[src] 为源码目录，[key] 为关键文件）")
    if result.truncated:
        lines.append("  注意：文件数量超限，列表已被截断")

    lines.append("")
    lines.append("=== 文件结构 ===")
    lines.extend(result.file_tree)

    return "\n".join(lines)
