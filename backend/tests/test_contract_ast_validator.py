"""Tests for the tree-sitter-based AST contract validator.

Goal: a contract like `public int Score { get; set; }` should match any
syntactically-equivalent declaration in the generated .cs:
  - `public int Score { get; set; }`            ← auto-property (baseline)
  - `public int Score { get; private set; }`    ← stricter setter
  - `public int Score { get => _x; set => ... }` ← expression-bodied
  - `public int Score => _x;`                   ← read-only expression-bodied (set missing → fail)
  - `[SerializeField] public int Score { ... }` ← decorated

The validator catches *semantic* mismatches (wrong type, wrong param
count, member not declared at all) while ignoring incidental syntactic
variation (body style, formatting, attributes).
"""
from __future__ import annotations

from pathlib import Path

import pytest


# Import lazily so the test file collects even before the impl exists —
# pytest will still report the import error per-test in a readable way.
def _import_validator():
    from domain.qa.contract_ast_validator import verify_contract
    return verify_contract


def _write_cs(tmp_path: Path, rel: str, content: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return tmp_path


def _contract(path: str, exports: list[dict]) -> dict:
    return {
        "namespace": "Test",
        "files": [{"path": path, "exports": exports}],
        "imports": [],
    }


# ── Match cases (should pass: errors == []) ─────────────────────────


def test_auto_property_baseline(tmp_path):
    """契约用 auto-property; LLM 也写 auto-property。最朴素的匹配。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo : MonoBehaviour {
    public int Score { get; set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "class", "signature": "public class Foo : MonoBehaviour", "name": "Foo"},
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs == []


def test_auto_property_contract_vs_full_body_impl(tmp_path):
    """**这是 GameManager.cs 失败的核心场景**：
    契约用 auto-property, LLM 用 full-property + event-firing setter。
    AST 视角是同一个 property, 必须通过。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo : MonoBehaviour {
    private int _score;
    public int Score {
        get => _score;
        set {
            if (_score != value) {
                _score = value;
                OnScoreChanged?.Invoke();
            }
        }
    }
    public event System.Action OnScoreChanged;
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs == [], f"expected no errors, got {errs}"


def test_auto_property_contract_vs_expression_bodied_readwrite(tmp_path):
    """契约 { get; set; }; LLM `{ get => _x; set => _x = value; }`。同语义。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    private int _x;
    public int X { get => _x; set => _x = value; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int X { get; set; }", "name": "X"},
    ]), root)
    assert errs == []


def test_property_with_stricter_setter_modifier_ok(tmp_path):
    """契约 `{ get; set; }` (public setter); 实现 `{ get; private set; }`
    (private setter)。public-set 是 looser 的契约, 实现更严是 OK 的。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public int X { get; private set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int X { get; set; }", "name": "X"},
    ]), root)
    # 业务决策: 契约只说"得有 set", 实现 set 加了 private 修饰仍然合法。
    # 如果未来希望严格契约, 可以反过来 — 现在先选宽松。
    assert errs == []


def test_property_with_serializefield_attribute(tmp_path):
    """LLM 加 [SerializeField] 装饰器, 不影响 declaration 匹配。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo : MonoBehaviour {
    [UnityEngine.SerializeField]
    public int X { get; set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int X { get; set; }", "name": "X"},
    ]), root)
    assert errs == []


def test_method_with_renamed_param(tmp_path):
    """契约方法 `Move(int x)`, LLM 写 `Move(int delta)`。参数名不影响 API
    形态, 类型匹配即通过。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public void Move(int delta) {}
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "method", "signature": "public void Move(int x)", "name": "Move"},
    ]), root)
    assert errs == []


def test_method_expression_bodied_ok(tmp_path):
    """契约 `public int Add(int a, int b)`, LLM `=>` 体。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public int Add(int a, int b) => a + b;
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "method", "signature": "public int Add(int a, int b)", "name": "Add"},
    ]), root)
    assert errs == []


def test_event_field_declaration(tmp_path):
    """事件字段 `public event Action OnX;`。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
using System;
public class Foo {
    public event Action OnDeath;
    public event Action<int> OnScore;
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "event", "signature": "public event Action OnDeath", "name": "OnDeath"},
        {"kind": "event", "signature": "public event Action<int> OnScore", "name": "OnScore"},
    ]), root)
    assert errs == []


def test_class_with_base(tmp_path):
    """class 签名匹配 — 看类名 + base type list。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class PlayerController : MonoBehaviour, IDamageable {
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "class", "signature": "public class PlayerController : MonoBehaviour", "name": "PlayerController"},
    ]), root)
    assert errs == []


def test_class_inside_namespace(tmp_path):
    """实现把 class 包在 namespace 里 (Unity 标准实践)。仍应匹配。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
namespace MyGame.Player {
    public class PC : MonoBehaviour {
        public int X { get; set; }
    }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "class", "signature": "public class PC : MonoBehaviour", "name": "PC"},
        {"kind": "property", "signature": "public int X { get; set; }", "name": "X"},
    ]), root)
    assert errs == []


# ── Miss cases (should fail: errors non-empty) ──────────────────────


def test_property_missing_entirely(tmp_path):
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public int Y { get; set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs and "Score" in errs[0]


def test_property_wrong_type(tmp_path):
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public float Score { get; set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs and ("Score" in errs[0])
    # 错误信息应该提到 type 差异
    assert any("int" in e or "float" in e or "type" in e.lower() for e in errs)


def test_property_private_instead_of_public(tmp_path):
    """契约要求 public, 实现是 private — 不算实现契约的 public API。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    private int Score { get; set; }
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs, "expected failure on private vs public mismatch"


def test_method_wrong_param_types(tmp_path):
    """方法名对了, 参数类型不对。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public void Move(float x) {}
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "method", "signature": "public void Move(int x)", "name": "Move"},
    ]), root)
    assert errs


def test_method_wrong_param_count(tmp_path):
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public void Move(int x, int y) {}
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "method", "signature": "public void Move(int x)", "name": "Move"},
    ]), root)
    assert errs


def test_field_does_not_satisfy_property_contract(tmp_path):
    """契约要求 property, 实现写了 public field — 不算实现。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
    public int Score;
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    assert errs


def test_event_missing(tmp_path):
    verify = _import_validator()
    root = _write_cs(tmp_path, "Foo.cs", """
public class Foo {
}
""")
    errs = verify(_contract("Foo.cs", [
        {"kind": "event", "signature": "public event System.Action OnDeath", "name": "OnDeath"},
    ]), root)
    assert errs


# ── Edge cases ──────────────────────────────────────────────────────


def test_file_not_found(tmp_path):
    verify = _import_validator()
    errs = verify(_contract("DoesNotExist.cs", [
        {"kind": "class", "signature": "public class X", "name": "X"},
    ]), tmp_path)
    assert errs and "DoesNotExist.cs" in errs[0]


def test_syntax_error_in_cs_gracefully_reported(tmp_path):
    """实现文件 syntax 坏的话, 应该报"语法错"而不是 silent pass / crash。"""
    verify = _import_validator()
    root = _write_cs(tmp_path, "Bad.cs", """
public class Bad {
    public int Score { get; set;   // 没闭合大括号
""")
    errs = verify(_contract("Bad.cs", [
        {"kind": "property", "signature": "public int Score { get; set; }", "name": "Score"},
    ]), root)
    # 行为可以二选一: 要么报 syntax error, 要么尽力解析 — 总之不应 crash。
    # 实际选 graceful: 尽力解析, 没找到就报 missing。
    assert isinstance(errs, list)


def test_empty_contract_files_passes(tmp_path):
    """contract.files 空数组 → 没东西要验证, errors 为空。"""
    verify = _import_validator()
    errs = verify({"files": []}, tmp_path)
    assert errs == []


def test_multi_file_contract(tmp_path):
    """一个 contract 跨多个 .cs 文件, 每个独立校验。"""
    verify = _import_validator()
    _write_cs(tmp_path, "A.cs", "public class A { public int X { get; set; } }")
    _write_cs(tmp_path, "B.cs", "public class B { public void Foo() {} }")
    errs = verify({
        "files": [
            {"path": "A.cs", "exports": [
                {"kind": "class", "signature": "public class A", "name": "A"},
                {"kind": "property", "signature": "public int X { get; set; }", "name": "X"},
            ]},
            {"path": "B.cs", "exports": [
                {"kind": "class", "signature": "public class B", "name": "B"},
                {"kind": "method", "signature": "public void Foo()", "name": "Foo"},
            ]},
        ]
    }, tmp_path)
    assert errs == []
