import ast
import json
import pathlib


def _rng(node: ast.AST) -> dict:
    return {
        "start": getattr(node, "lineno", None),
        "end": getattr(node, "end_lineno", None),
    }


def main() -> None:
    path = pathlib.Path("services/ceo_advisor_agent.py")
    src = path.read_text(encoding="utf-8")
    mod = ast.parse(src)

    classes = []
    functions = []
    globals_ = []

    for node in mod.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(
                        {
                            "name": item.name,
                            "async": isinstance(item, ast.AsyncFunctionDef),
                            "public": not item.name.startswith("_"),
                            **_rng(item),
                        }
                    )
            classes.append({"name": node.name, **_rng(node), "methods": methods})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "public": not node.name.startswith("_"),
                    **_rng(node),
                }
            )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t.id)
            else:
                if isinstance(node.target, ast.Name):
                    targets.append(node.target.id)
            if targets:
                globals_.append({"targets": targets, **_rng(node)})

    out = {
        "file": str(path).replace("\\\\", "/"),
        "classes": classes,
        "functions": functions,
        "globals": globals_,
    }

    out_path = pathlib.Path("_tmp_ceo_advisor_agent_defs.json")
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"WROTE {out_path}")
    print(f"classes={len(classes)} functions={len(functions)} globals={len(globals_)}")


if __name__ == "__main__":
    main()
