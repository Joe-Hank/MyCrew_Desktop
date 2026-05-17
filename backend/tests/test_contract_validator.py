"""Tests for V5 Stage B contract verification."""
from __future__ import annotations

from pathlib import Path

import pytest

from domain.qa.contract_validator import normalize_csharp, verify_contract


def test_normalize_strips_comments_and_collapses_whitespace():
    source = """
    // single-line comment
    public  class /* inline */
       PlayerController : MonoBehaviour
    {
        /* block
           comment */
        public  void  Move(Vector2 d) { }
    }
    """
    out = normalize_csharp(source)
    assert "PlayerController : MonoBehaviour" in out
    assert "public void Move(Vector2 d)" in out
    # No double spaces anywhere
    assert "  " not in out
    # Comments are gone
    assert "single-line" not in out
    assert "block" not in out
    assert "inline" not in out


def test_verify_passes_when_all_signatures_present(tmp_path: Path):
    target = tmp_path / "Scripts" / "PlayerController.cs"
    target.parent.mkdir(parents=True)
    target.write_text(
        """
using UnityEngine;
public class PlayerController : MonoBehaviour
{
    public event System.Action OnDeath;
    public void Move(Vector2 direction) { transform.position += (Vector3)direction; }
}
""",
        encoding="utf-8",
    )
    contract = {
        "files": [{
            "path": "Scripts/PlayerController.cs",
            "exports": [
                {"kind": "class", "signature": "public class PlayerController : MonoBehaviour"},
                {"kind": "method", "signature": "public void Move(Vector2 direction)"},
                {"kind": "event", "signature": "public event System.Action OnDeath"},
            ],
        }],
    }
    assert verify_contract(contract, tmp_path) == []


def test_verify_reports_missing_method(tmp_path: Path):
    target = tmp_path / "Scripts" / "PlayerController.cs"
    target.parent.mkdir(parents=True)
    target.write_text(
        "public class PlayerController : MonoBehaviour {}",
        encoding="utf-8",
    )
    contract = {
        "files": [{
            "path": "Scripts/PlayerController.cs",
            "exports": [
                {"kind": "class", "signature": "public class PlayerController : MonoBehaviour"},
                {"kind": "method", "signature": "public void Jump(float height)"},
            ],
        }],
    }
    errors = verify_contract(contract, tmp_path)
    assert len(errors) == 1
    assert "Jump" in errors[0]
    assert "PlayerController.cs" in errors[0]


def test_verify_reports_missing_file(tmp_path: Path):
    contract = {
        "files": [{
            "path": "Scripts/NotExist.cs",
            "exports": [{"kind": "class", "signature": "public class X"}],
        }],
    }
    errors = verify_contract(contract, tmp_path)
    assert len(errors) == 1
    assert "NotExist.cs" in errors[0]
    assert "不存在" in errors[0] or "不存在" in str(errors[0])


def test_verify_handles_multiline_method_header(tmp_path: Path):
    """Crew may emit method headers across multiple lines; the
    normalization step should collapse them so the single-line contract
    signature still matches."""
    target = tmp_path / "X.cs"
    target.write_text(
        """
public class X
{
    public void Move(
        Vector2 direction,
        float speed)
    {
    }
}
""",
        encoding="utf-8",
    )
    contract = {
        "files": [{
            "path": "X.cs",
            "exports": [
                {"kind": "method",
                 "signature": "public void Move(Vector2 direction, float speed)"},
            ],
        }],
    }
    assert verify_contract(contract, tmp_path) == []


def test_verify_returns_empty_for_empty_contract(tmp_path: Path):
    assert verify_contract({"files": []}, tmp_path) == []
    assert verify_contract({}, tmp_path) == []


def test_verify_ignores_signature_inside_comment(tmp_path: Path):
    """A class signature that only appears in a comment should NOT
    count as defined. (Comments are stripped before matching.)"""
    target = tmp_path / "X.cs"
    target.write_text(
        """
// public class Ghost : MonoBehaviour  ← this is a comment, doesn't count
public class Real : MonoBehaviour {}
""",
        encoding="utf-8",
    )
    contract = {
        "files": [{
            "path": "X.cs",
            "exports": [{"kind": "class",
                         "signature": "public class Ghost : MonoBehaviour"}],
        }],
    }
    errors = verify_contract(contract, tmp_path)
    assert len(errors) == 1
    assert "Ghost" in errors[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
